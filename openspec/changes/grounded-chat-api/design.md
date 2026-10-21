# Design

## Context

Мотивация и границы этапа — в `proposal.md`; contract — в `specs/grounded-chat-api/spec.md`. Использован весь brief §10 ROADMAP.md и SPEC.md §§5,10–16,18,20,24,26–27. §17 учитывается только для token budget и границы следующего этапа.

Наблюдаемая реализация:

- `main.py` в lifespan вызывает `load_index_state`; `/health` возвращает только `{"status":"ok"}`. `__main__.py` запускает Uvicorn с `workers=1`.
- `ActiveIndex` удерживает `LexicalReader`, validated snapshot/matrix, ordered IDs, semantic/lexical metadata и reindex metadata до shutdown. Это ещё не HTTP retrieval service и не encoder.
- `HybridIndex` самостоятельно открывает `LexicalReader`, строит semantic и lexical readers одного поколения, использует локальный `LocalEncoder`; `.search()` возвращает `HybridResult` со `StoredChunk`. Reader содержит SQLite connection; `last_branch_union` — mutable per-search состояние. Нельзя просто вызывать общий экземпляр из произвольных threads.
- `RetrievalSettings` уже имеет defaults 10/10/60/6 и environment overrides. Semantic query проверяет полный E5 input ≤512 tokens без truncation.
- `StoredChunk` содержит document, heading path, source ranges, segments и `search_text`. Последний может содержать generated table headers/fences. `Document` хранит исходный Markdown и backend-generated `source_url`.
- `llm_check.py` — административная urllib smoke-команда, а не request client. Она уже использует origin `LLM_BASE_URL`, alias, max tokens, temperature=0.2, top_p=0.8, top_k=20 и отключает proxies. Ни prompt builder, ни chat route, ни LLM token counter пока не реализованы.
- Compose передаёт retrieval/model settings, держит LLM без published ports, CPU-only, parallel=1, read-only GGUF. `LLM_CONTEXT_SIZE` сейчас задаётся только стороне llm; app должен получить то же значение.
- `eval/questions.yaml` уже содержит IDs, required facts/evidence ranges, exact commands, splits, source sets и expected behavior; это frozen input, а не новый список для tuning.

В `openspec/specs/hybrid-retrieval/spec.md` requirement `Measured quality acceptance and tuning discipline` всё ещё называет ≥90% обязательным MVP-критерием. Это противоречит действующим SPEC.md §§12.5,27,30 и ROADMAP.md. Здесь применяется установленный пользователем приоритет SPEC.md: численный порог не блокирует grounded API, misses остаются обязательной частью отчёта. Данный change не меняет ranking или исторический quality acceptance и не переписывает старые specs/эксперименты; расхождение явно раскрыто для review.

## Goals / Non-Goals

**Goals:** получить один проверяемый путь через существующий индекс, оригинальные fragments, локальную модель и backend validation; сохранить startup без model assets и избежать смешивания поколений/SQLite threads.

**Non-Goals:** session storage/follow-up, UI/health expansion, streaming, автоматические retries, tools, verifier model, semantic entailment checker, retrieval tuning/reranker, миграция storage schema. Ограничения источников не компенсируются знаниями модели.

## Decisions

### 1. Тонкий HTTP route и независимый typed chat service

Добавить небольшие модули `chat.py` (orchestration и typed result), `grounding.py` (context/validators) и `llm_client.py` (transport/token counting); точное распределение вспомогательных функций допускает минимизацию при реализации. Route принимает strict strings session_id/message, отбрасывает whitespace-only, использует текущий вопрос без session memory. Ограничить `session_id` 128 Unicode code points, `message` — 4096 Unicode code points: считать исходную декодированную строку до trim, включая пробелы, без молчаливого сокращения. Это простые фиксированные ограничения request models, без нового сервиса/конфигурационного слоя; E5/LLM token budgets проверяются дополнительно и могут отклонить более короткий текст. Значение ровно на лимите проходит проверку длины, превышение даёт безопасную 422 до retrieval/model calls. Response сохраняет форму SPEC §20. Ошибки request validation преобразуются в безопасные 422 без стандартного echo `input`.

Технический mapping: index/assets/retrieval/configuration/LLM unavailable → 503; timeout → 504; invalid transport JSON/envelope, alias mismatch или пустой message content → 502. Валидный envelope с невалидным форматом сгенерированного текста → безопасный неподтверждённый HTTP 200. Это отделяет инфраструктурную ошибку от недостатка Wiki evidence. Публичный reindex route не создаётся.

Альтернатива — сразу реализовать §17 или менять response schema под history — увеличивает этап и смешивает его с `session-follow-up`.

### 2. Один владелец SQLite и lazy encoder

Создать при lifespan один выделенный single-thread executor для active index/retrieval. В нём загрузить `IndexState`, там же создавать lazy encoder, выполнять search и закрывать readers при shutdown. Снаружи читать только immutable status/result data. Первый chat инициализирует encoder и settings в этом executor; отсутствие/ошибка assets не ломает startup/health и не запускает downloads.

Добавить минимальный способ построить hybrid view из уже удерживаемого `ActiveIndex`/его reader, используя существующие `_from_base`/`_from_reader` patterns и validated matrix. Не открывать путь заново между фазами запроса; сохранять current snapshot до restart. Владение закрытием остаётся у IndexState. Standalone `HybridIndex(path, encoder, settings)` и CLI сохраняются. Весь доступ к shared SQLite reader и `last_branch_union` последователен в одном executor; в coroutine возвращается immutable tuple результатов. При нескольких chat запросах retrieval может выполняться, пока другой запрос ждёт/получает LLM, но два поиска на общем reader не выполняются одновременно.

Это точечная integration, без глобального `check_same_thread=False`, новых соединений на каждый запрос, hot reload и переписывания storage. Для небольшого корпуса последовательный retrieval приемлем; benchmark покажет стоимость. Отмена await не закрывает занятой reader; shutdown дожидается текущей операции.

### 3. Исходный context manifest

После retrieval сформировать request-local manifest в rank order: chunk ID → metadata и набор `document.markdown[start:end]` для source ranges. Соседние/перекрывающиеся ranges одного chunk можно объединять только если получается непрерывный исходный интервал. Generated segments не входят в evidence; `search_text` остаётся retrieval representation.

Prompt содержит фиксированные system rules, вопрос и явно отделённую секцию недоверенных CONTEXT data с ID и отдельными fragments. Использовать JSON serialization для данных с escaping, чтобы текст документа с псевдо-delimiters не становился структурой prompt. Title/headings также недоверенные данные. URL модели для citations не нужен; backend берёт `source_url` из Document без добавления выдуманного heading anchor.

Manifest замораживается после budget packing. Только его IDs/ranges доступны citation/code validators. Не разрешать lookup по произвольному ID из всей БД или цитирование всего документа вместо переданного fragment.

Альтернатива — передать/цитировать `search_text` — проще, но смешивает реальные source fragments с generated fences/headers и нарушает provenance.

### 4. Точное budget accounting через обслуживающий llama.cpp

Первой задачей блока 2, до реализации LLM client/token counter, провести live compatibility smoke на уже закреплённом llama.cpp image и установленной модели без изменения image, runtime flags или chat template. Для одинаковых messages проверить цепочку `/apply-template` → `/tokenize` относительно фактического `usage.prompt_tokens` из `/v1/chat/completions`, включая generation prefix и special tokens. Критерий — точное целочисленное равенство, без допуска и поправочного коэффициента, на коротком русском prompt и prompt с несколькими CONTEXT fragments, code/Unicode и служебным форматом. Исключить влияние prompt cache (разные prompts/отключение cache только параметром диагностического запроса, если поддерживается); не считать cached-only timing counters полным prompt usage. Сохранить digest, model identity, request/tokenization options и пары calculated/actual counts в `docs/grounded-chat-api-server-acceptance.md`. Если usage отсутствует, endpoints несовместимы либо counts расходятся, задача не выполнена: остановить зависимые задачи блока 2 и согласовать корректный точный путь, не менять runtime и не вводить приблизительный подсчёт. При отсутствии live-доступа оставить 2.1 открытой; fake server её не заменяет.

После успешной проверки использовать ту же цепочку для полного массива messages, который уйдёт в completion. Не добавлять второй HF tokenizer и не загружать assets из сети. Финальная приёмка повторяет проверку на окончательном prompt и границах бюджета, но не заменяет ранний compatibility gate.

Передать `LLM_CONTEXT_SIZE` app из того же Compose значения, что `--ctx-size`; в typed settings валидировать положительные window/reserve и `reserve < window`. Default 8192/768. `LLM_MAX_TOKENS` определяет резерв и request max_tokens. Проверить минимальный prompt без chunks: если он не помещается, 422 с просьбой сократить вопрос. Затем проверять prompt с top-k и убирать последний chunk целиком, пока `prompt_tokens + reserve <= context_size`; не обрезать source или code block. При пустом packed context — стандартный отказ без completion. Штатная empty retrieval также возвращает отказ после существующих query/model checks.

Недоступность tokenizer/template endpoints — техническая ошибка 503/504, сломанный protocol — 502; не masked refusal. Результат token count не логирует prompt. Проверка E5 остаётся в существующем encode_query; overflow становится понятной 422.

### 5. Один completion со структурированным содержимым

System prompt требует один JSON object вида `{"kind":"answer|partial|refuse|clarify","answer":"... [chunk:<chunk_id>]"}`. Это внутренний формат, наружу выходит обычный API response. Backend проверяет allowed kind, непустой answer и единственный object; raw output/fences вокруг JSON не публикуются. На первом варианте достаточно строгого prompt и parser без provider abstraction или дополнительной модели. Если модель не соблюдает формат, возвращается безопасный fallback; реальная приёмка проверяет пригодность этого решения.

`answer` и `partial` требуют хотя бы одну валидную citation; `partial`, `refuse`, `clarify` дают insufficient_context=true. Для `refuse` backend выводит стандартную фразу без свободных фактических утверждений модели. `clarify` разрешает только короткое уточнение; отсутствие скрытых фактов проверяется на corpus вручную. Ответ с противоречиями оформляется kind=partial с обоими цитированными вариантами. Никакой численный score threshold не заменяет оценку достаточности моделью и ручную проверку.

LLM client использует стандартный HTTP transport без дополнительных runtime dependencies: JSON, alias из settings, stream=false, прежние sampling defaults, конечный configurable `LLM_TIMEOUT_SECONDS` default 300. Base URL — административный HTTP origin без credentials/path/query; proxies отключены. Клиент не передаёт tools, не следует redirect на другой origin и не делает auto-retry. App не подключается к Wiki.js из chat.

Альтернатива — свободный текст плюс regex определения отказа — хуже отделяет partial/refusal/clarify. Grammar/JSON-schema mode допустим только как последующая совместимая оптимизация после измерения; он не заменяет проверки grounding.

### 6. Проверка citations и кода перед публикацией

Проверять весь answer на malformed/unknown citation markers. Для каждого использованного chunk backend выпускает source entries по непрерывным исходным ranges и заменяет marker на соответствующие номера `[1] [2]`; повторные ссылки на chunk используют те же номера. Порядок sources — первое появление chunk в answer, ranges внутри него — исходный порядок. Одинаковый документ с разными chunks не сводить к одной page citation. `heading` — join heading_path через ` > ` либо пустая строка. Quote — исходный slice; модель не выбирает quote или URL.

Сгенерированные markdown source links вместо chunk markers не принимаются. Технические URL literals внутри дословного source code не становятся source links и проходят ту же code validation. Каждый fenced block проверяется отдельно: убрать opening/closing fences, language marker и один delimiter newline перед closing fence; остальное должно целиком присутствовать в одном переданном непрерывном source fragment. Не нормализовать пробелы, переводы строк, параметры, IP или identifiers. Незакрытые/неправильно сформированные fences также отклоняются. Prompt требует показывать команды в fences; backend не заявляет, что умеет надёжно найти любую команду, спрятанную в обычной прозе.

Любая неверная citation, отсутствие citation у substantive kind, невалидный code block или malformed generated object заменяет весь сгенерированный answer безопасным сообщением «Не удалось подтвердить ответ по найденным источникам. Откройте источники ниже.» и sources из packed manifest. Не оставлять рядом неподтверждённые утверждения и не пытаться исправлять модель второй генерацией. Это консервативнее удаления одного code block, зато не оставляет потенциально связанную опасную инструкцию в прозе.

### 7. Semaphore, timeout и безопасные timings

Использовать один process-wide `asyncio.Semaphore(1)` на фазу model interaction: template/tokenize/packing и completion. Retrieval выполняется до захвата. Transport — blocking urllib в worker thread, event loop остаётся свободным для `/health` и ожидания. Счётчик wait начинается перед semaphore, generation duration включает только completion transport; token budgeting можно измерять отдельно. Query/retrieval/wait/generation durations пишутся структурированными безопасными полями, без текста вопроса, session_id, prompts или credentials.

Ожидание semaphore не ограничивается 300-секундным completion timeout: несколько минут очереди допустимы SPEC §18. Примеры curl/клиентов должны учитывать очередь. При cancellation защищённая transport task остаётся владельцем semaphore до подтверждённого завершения генерации, а не только завершения coroutine/thread. Полный ответ completion подтверждает завершение; закрытие HTTP socket, timeout, network error после возможной отправки completion и `/health: ok` сами по себе этого не подтверждают. Ошибка до отправки completion либо ошибка только template/tokenize не оставляет активной генерации и допускает обычное освобождение слота.

Если HTTP timeout наступил после возможной отправки completion, клиент получает 504, но logical generation slot не освобождается: установить process-local состояние `generation_uncertain`, удерживать semaphore и не посылать новых completions. Уже ожидающие запросы пробуждаются с безопасной 503, новые также сразу получают 503; event уведомления о состоянии вместе с имеющимся semaphore достаточны, отдельная очередь/сервис не нужны. При сетевом обрыве с неопределённым завершением применяется то же состояние (исходный запрос получает техническую 503). Если HTTP-клиент отменён, но фоновый transport получил полный ответ, слот можно освободить; если transport завершился timeout/обрывом, действует та же блокировка. Одно лишь течение времени, health-check или `--parallel 1` не разрешают release: backend не должен посылать следующую генерацию, даже если сервер способен поставить её в свою очередь.

В этом этапе не добавлять runtime flags, polling непроверенного slot API или автоматический restart/cancel llama-server. Без надёжного подтверждения завершения выбран безопасный ручной recovery: оператор подтверждает остановку прежнего llama-server процесса, штатно запускает LLM и затем перезапускает app. Один restart app без подтверждённого прекращения старой генерации не является recovery. До этого chat недоступен, `/health` сохраняет прежний app-only контракт; лог содержит только безопасную категорию и необходимость recovery. Ошибка гарантированно до отправки completion и полный ответ проверяются отдельно, чтобы не блокировать сервис из-за любого локального validation failure.

Shutdown прекращает приём работы и дожидается bounded локальных transports перед закрытием executor/index; для uncertain generation не заявляет, что удалённая работа завершилась, и не ждёт её бесконечно. Не использовать автоматический retry после timeout. Документировать, что `llama-server --parallel 1` сохраняется как дополнительное ограничение runtime, а не механизм восстановления application semaphore.

### 8. Приёмка без изменения retrieval experiment

Unit/API tests используют injected fake encoder/LLM/token counter и маленький temporary SQLite index, проверяют реальные границы validator и orchestration, не требуют GPU/интернета. Integration checks подтверждают действительные stored source slices и общую generation identity.

На целевом CPU выполнить все single-question evaluation cases из текущего frozen corpus, включая все answerable=false; follow-up отдельно указать «не входит в этот этап». Для synthetic conflict/partial/injection использовать существующие eval fixtures, а недостающие boundary/security cases добавлять только в новые test fixtures, не менять frozen expectations. Раздельно проверить (а) end-to-end текущий retrieval и (б) generation с фиксированным достаточным evidence из frozen ranges, чтобы различать retrieval/context misses и generation defects. Второй режим — только test/admin harness, без публичного context override.

Человек оценивает required facts, поддержку каждого утверждения citations, exact commands, refusal и отсутствие успешной injection. В отдельном `docs/grounded-chat-api-server-acceptance.md` сохранить case verdicts, settings/model/image/index/corpus identity, реальные timings, ограничения и отсутствие UI/history; не копировать весь corpus/secrets в logs. ≥90% Hit@5 не является gate; полный grounded ответ по фактически достаточному context и безопасный отказ при недостаточном — gate. Отчёт не объявляет ни весь MVP завершённым, ни строгий prompt гарантией отсутствия будущих ошибок.

## Risks / Trade-offs

- [Валидная citation не доказывает entailment; команда может оказаться вне fences] → строгие правила, exact-block checks и ручной review corpus; не заявлять автоматическую гарантию всех фактов.
- [Малая Qwen нарушает JSON/prompt/injection rules] → консервативный fallback и реальные server checks; невыполненная grounded acceptance остаётся открытой задачей, без verifier model или незаметной смены модели.
- [Token endpoints/chat template отличаются между llama.cpp builds] → compatibility smoke с полным шаблоном на установленном image и явная техническая ошибка при несовместимости, без character heuristic.
- [Очередь CPU повышает latency] → один worker, отдельные wait/generation timings, 300s transport timeout и документированный длительный client timeout; не увеличивать parallelism без нового решения.
- [Полные исходные ranges в sources увеличивают response] → top-k и context budget ограничивают объём; точность provenance важнее сокращения цитат моделью.
- [Страница по URL изменилась после reindex] → docs поясняют snapshot semantics: quote относится к index generation, ссылка открывает текущую Wiki.js страницу.
- [Основная hybrid spec содержит старый MVP quality gate] → раскрытое расхождение разрешается приоритетом SPEC.md в этом plan; исторические результаты и ranking не меняются.

## Migration Plan

1. После review выполнить ранний live gate 2.1 на неизменном закреплённом runtime до реализации зависимого LLM client/token counter; после его успеха реализовать route/service и профильные checks. SQLite schema и существующий индекс сохраняются.
2. Добавить app settings и Compose environment для context/timeout, описать запросы/ошибки в новом docs-файле и `.env.example`; не менять README/ROADMAP.
3. Проверить app-only, затем подготовленные offline assets/image, повторную template/tokenize compatibility на окончательном prompt, end-to-end chat, concurrency и timeout/recovery на целевом сервере. Проверить отсутствие published LLM port и отсутствие Wiki.js writes/network calls из chat.
4. При rollback вернуть предыдущий app image/code и environment; индекс не мигрировал и остаётся совместимым. Внешних записей, которые нужно откатывать, нет.
