# Design

> Review draft, 2026-10-22: изменяется область критериев MVP, без реализации до
> согласования. Приоритеты и порядок gates ниже заменяют прежний общий semantic
> acceptance gate; результаты прежних прогонов остаются историческими фактами.

## Context

Мотивация и границы этапа — в `proposal.md`; contract — в `specs/grounded-chat-api/spec.md`. Использован весь brief §10 ROADMAP.md и SPEC.md §§5,10–16,18,20,24,26–27. §17 учитывается только для token budget и границы следующего этапа.

Наблюдаемая реализация:

- `main.py` в lifespan создаёт `RetrievalService` и `ChatService`, вызывает `retrieval.start()` и подключает chat router; `/health` возвращает только `{"status":"ok"}`. `__main__.py` запускает Uvicorn с `workers=1`.
- `ActiveIndex` удерживает `LexicalReader`, validated snapshot/matrix, ordered IDs, semantic/lexical metadata и reindex metadata до shutdown. Реализованный `RetrievalService` владеет выделенным single-thread executor, в котором загружает `IndexState`, лениво создаёт encoder/hybrid view и выполняет search/close.
- `HybridIndex` самостоятельно открывает `LexicalReader`, строит semantic и lexical readers одного поколения, использует локальный `LocalEncoder`; `.search()` возвращает `HybridResult` со `StoredChunk`. Reader содержит SQLite connection; `last_branch_union` — mutable per-search состояние. Нельзя просто вызывать общий экземпляр из произвольных threads.
- `RetrievalSettings` уже имеет defaults 10/10/60/6 и environment overrides. Semantic query проверяет полный E5 input ≤512 tokens без truncation.
- `StoredChunk` содержит document, heading path, source ranges, segments и `search_text`. Последний может содержать generated table headers/fences. `Document` хранит исходный Markdown и backend-generated `source_url`.
- `llm_check.py` остаётся административной smoke-командой. Request transport и точный `/apply-template` → `/tokenize` counter реализованы в `LLMClient`, prompt/packing/validators — в `grounding.py`, orchestration/generation gate — в `ChatService`, HTTP contract — в `chat_api.py`. Прежние alias, max tokens, temperature=0.2, top_p=0.8, top_k=20 и отключённые proxies сохраняются.
- Compose передаёт retrieval/model settings, держит LLM без published ports, CPU-only, parallel=1, read-only GGUF. App и llm уже получают согласованное `LLM_CONTEXT_SIZE`; конфигурация этим review не меняется.
- `eval/questions.yaml` уже содержит IDs, required facts/evidence ranges, exact commands, splits, source sets и expected behavior; это frozen input, а не новый список для tuning.

В `openspec/specs/hybrid-retrieval/spec.md` requirement `Measured quality acceptance and tuning discipline` всё ещё называет ≥90% обязательным MVP-критерием. Это противоречит действующим SPEC.md §§12.5,27,30 и ROADMAP.md. Здесь применяется установленный пользователем приоритет SPEC.md: численный порог не блокирует grounded API, misses остаются обязательной частью отчёта. Данный change не меняет ranking или исторический quality acceptance и не переписывает старые specs/эксперименты; расхождение явно раскрыто для review.

## Goals / Non-Goals

**Goals:** получить стабильный и предсказуемый путь через существующий индекс, оригинальные fragments, локальную модель и backend validation; сохранить startup без model assets и избежать смешивания поколений/SQLite threads. На оставшейся приёмке сначала проверить ресурсы/LLM, затем очередь/recovery и isolation, после этого итоговый live MVP contract.

**Non-Goals:** session storage/follow-up, UI/health expansion, streaming, автоматические retries, tools, verifier model, semantic entailment checker, retrieval tuning/reranker, миграция storage schema. Ограничения источников не компенсируются знаниями модели.

Полнота required facts, семантическая обоснованность kind и entailment допустимых
citations перенесены в post-MVP SPEC §27. Дополнительные механизмы смысловой проверки
не входят в этап. `parts` не реализуется и не предписывается для post-MVP. Правила
prompt и существующие validators/fail-closed не ослабляются; команды, отсутствие
выдуманных фактов на unanswerable, conflict/injection safety и read-only остаются
MVP gates. Смена приоритета не означает принятие этих проверок или исправление
известных quality failures.

## Decisions

### 1. Тонкий HTTP route и независимый typed chat service

Реализованы `chat.py` (orchestration и typed result), `grounding.py` (context/validators), `llm_client.py` (transport/token counting) и `chat_api.py` (HTTP contract). Route принимает strict strings session_id/message, отбрасывает whitespace-only, использует текущий вопрос без session memory. Лимиты `session_id` 128 Unicode code points, `message` — 4096 Unicode code points применяются к исходной декодированной строке до trim, включая пробелы, без молчаливого сокращения. Это фиксированные ограничения request models, без нового сервиса/конфигурационного слоя; E5/LLM token budgets проверяются дополнительно и могут отклонить более короткий текст. Значение ровно на лимите проходит проверку длины, превышение даёт безопасную 422 до retrieval/model calls. Response сохраняет форму SPEC §20. Ошибки request validation преобразуются в безопасные 422 без стандартного echo `input`.

Технический mapping: index/assets/retrieval/configuration/LLM unavailable → 503; timeout → 504; invalid transport JSON/envelope, alias mismatch или пустой message content → 502. Валидный envelope с невалидным форматом сгенерированного текста → безопасный неподтверждённый HTTP 200. Это отделяет инфраструктурную ошибку от недостатка Wiki evidence. Публичный reindex route не создаётся.

Альтернатива — сразу реализовать §17 или менять response schema под history — увеличивает этап и смешивает его с `session-follow-up`.

### 2. Один владелец SQLite и lazy encoder

При lifespan `RetrievalService` создаёт один выделенный single-thread executor для active index/retrieval. В нём загружается `IndexState`, там же создаётся lazy encoder, выполняются search и закрытие readers при shutdown. Снаружи читаются только immutable status/result data. Первый chat инициализирует encoder и settings в этом executor; отсутствие/ошибка assets не ломает startup/health и не запускает downloads.

Hybrid view уже строится через `HybridIndex._from_active` из удерживаемого `ActiveIndex`/его reader и validated matrix. Путь не открывается заново между фазами запроса; current snapshot сохраняется до restart. Владение закрытием остаётся у IndexState. Standalone `HybridIndex(path, encoder, settings)` и CLI сохраняются. Весь доступ к shared SQLite reader и `last_branch_union` последователен в одном executor; в coroutine возвращается immutable tuple результатов. При нескольких chat запросах retrieval может выполняться, пока другой запрос ждёт/получает LLM, но два поиска на общем reader не выполняются одновременно.

Это точечная integration, без глобального `check_same_thread=False`, новых соединений на каждый запрос, hot reload и переписывания storage. Для небольшого корпуса последовательный retrieval приемлем; benchmark покажет стоимость. Отмена await не закрывает занятой reader; shutdown дожидается текущей операции.

### 3. Исходный context manifest

После retrieval сформировать request-local manifest в rank order: chunk ID → metadata и набор `document.markdown[start:end]` для source ranges. Соседние/перекрывающиеся ranges одного chunk можно объединять только если получается непрерывный исходный интервал. Generated segments не входят в evidence; `search_text` остаётся retrieval representation.

Prompt содержит фиксированные system rules, вопрос и явно отделённую секцию недоверенных CONTEXT data с ID и отдельными fragments. Использовать JSON serialization для данных с escaping, чтобы текст документа с псевдо-delimiters не становился структурой prompt. Title/headings также недоверенные данные. URL модели для citations не нужен; backend берёт `source_url` из Document без добавления выдуманного heading anchor.

Manifest замораживается после budget packing. Только его IDs/ranges доступны citation/code validators. Не разрешать lookup по произвольному ID из всей БД или цитирование всего документа вместо переданного fragment.

Альтернатива — передать/цитировать `search_text` — проще, но смешивает реальные source fragments с generated fences/headers и нарушает provenance.

### 4. Точное budget accounting через обслуживающий llama.cpp

Ранний live compatibility gate 2.1 выполнен до реализации LLM client/token counter
на закреплённом image/model без смены runtime flags/template. Проверена цепочка
`/apply-template` → `/tokenize` против `usage.prompt_tokens` для одинаковых messages,
с generation prefix/special tokens, коротким русским prompt и CONTEXT/code/Unicode.
Identity, options и exact calculated/actual counts сохранены в acceptance report;
fake-server tests не подменяют этот результат. Counter и client реализованы по
проверенному пути. При будущем изменении identity или mismatch запрещены approximate
counts/поправки и требуется отдельное согласование точного пути.

Counter использует ту же цепочку для полного массива messages, отправляемого в completion. Второго HF tokenizer и runtime downloads нет. Gate 7.1 также выполнен на окончательном prompt и границах бюджета; его результат сохраняется до изменения messages/runtime identity и не заменяет ранний compatibility gate.

`LLM_CONTEXT_SIZE` передаётся app из того же Compose значения, что `--ctx-size`; typed settings валидируют положительные window/reserve и `reserve < window`. Default 8192/768. `LLM_MAX_TOKENS` определяет резерв и request max_tokens. Packing проверяет минимальный prompt без chunks: если он не помещается, 422 с просьбой сократить вопрос. Затем проверяет prompt с top-k и убирает последний chunk целиком, пока `prompt_tokens + reserve <= context_size`, без обрезания source/code block. При пустом packed context — стандартный отказ без completion. Штатная empty retrieval также возвращает отказ после существующих query/model checks.

Недоступность tokenizer/template endpoints — техническая ошибка 503/504, сломанный protocol — 502; не masked refusal. Результат token count не логирует prompt. Проверка E5 остаётся в существующем encode_query; overflow становится понятной 422.

### 5. Один completion со структурированным содержимым

System prompt требует один JSON object вида `{"kind":"answer|partial|refuse|clarify","answer":"... [chunk:<chunk_id>]"}`. Это внутренний формат, наружу выходит обычный API response. Backend проверяет allowed kind, непустой answer и единственный object; raw output/fences вокруг JSON не публикуются. Сохраняются строгий prompt и parser без provider abstraction или дополнительной модели. Если модель не соблюдает формат, возвращается безопасный fallback; live MVP приёмка проверяет этот contract. Семантическая полнота и выбор kind регистрируются отдельным quality verdict, не исправляются backend по наличию citations.

`answer` и `partial` требуют хотя бы одну валидную citation; `partial`, `refuse`, `clarify` дают insufficient_context=true. Для `refuse` backend выводит стандартную фразу без свободных фактических утверждений модели. `clarify` разрешает только короткое уточнение; отсутствие скрытых фактов проверяется на corpus вручную. Ответ с противоречиями оформляется kind=partial с обоими цитированными вариантами. Никакой численный score threshold не заменяет оценку достаточности моделью и ручную проверку. Перенос качества kind не отменяет обязательных проверок unanswerable, конфликта и injection, не разрешает скрытые команды, ложные source metadata или обход validators.

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

### 8. Раздельная приёмка MVP и post-MVP качества

Unit/API tests используют injected fake encoder/LLM/token counter и маленький temporary SQLite index, проверяют реальные границы validator и orchestration, не требуют GPU/интернета. Integration checks подтверждают действительные stored source slices и общую generation identity.

На целевом CPU выполнить все single-question evaluation cases из текущего frozen corpus, включая все answerable=false; follow-up отдельно указать «не входит в этот этап». Для synthetic conflict/partial/injection использовать существующие eval fixtures, а недостающие boundary/security cases добавлять только в новые test fixtures, не менять frozen expectations. Раздельно проверить (а) end-to-end текущий retrieval и (б) generation с фиксированным достаточным evidence из frozen ranges, чтобы различать retrieval/context misses и generation defects. Второй режим — только test/admin harness, без публичного context override.

Человек оценивает required facts, поддержку каждого утверждения citations, exact
commands, refusal/conflict и отсутствие успешной injection. Отчёт разделяет три
вердикта: stability (ресурсы, transport, concurrency/recovery/offline), safety
(contract, validators/fallback, команды, unanswerable/ambiguity/conflict/injection,
isolation/read-only) и semantic quality (полнота, семантический kind, entailment).
MVP требует pass stability и safety. Только изолированный quality fail не блокирует
MVP, но остаётся открытым post-MVP дефектом, не становится pass. Если один ответ
нарушает safety и quality, неблокирующая метка quality не отменяет safety fail.
Технические ошибки не становятся refusal. Не приписывать sources
или исправленный insufficient_context в backend для улучшения verdict.

Известные q13 (неоднозначный объект) и q18 (противоречие) — потенциальные blockers
safety acceptance. q13 нельзя автоматически считать лишь ошибкой kind: нужно
отдельно оценить недопустимую подстановку объекта и выдуманный содержательный ответ.
q18 нельзя свести к неполноте: самостоятельный выбор варианта при неразрешённом
противоречии нарушает safety. До отдельного доказанного safety verdict эти cases
не переводятся в неблокирующее качество. Раскрытый q18 holdout используется только
как сохранённый результат/финальный safety review, не для настройки prompt, runtime,
validators или retrieval. Новая реализация по этому review не начинается.

В `docs/grounded-chat-api-server-acceptance.md` сохранить case verdicts, settings/
model/image/index/corpus identity, timings и ограничения. Прежние reviews и failed
7.2 сохраняются с исходными критериями; новое решение указывается отдельно с датой.
Раскрытый holdout не используется для tuning. ≥90% Hit@5 не является gate. Отчёт
не объявляет весь MVP продукта завершённым, семантическую приёмку успешной либо
строгий prompt гарантией отсутствия будущих ошибок. Уже проверенные неизменные
компоненты не проверяются заново без причины; 7.1 остаётся принятой, пока messages
и token/runtime identity прежние.

### 9. Стабильность LLM, global OOM и последовательная memory series

Порядок оставшихся gates: 7.5 (диагностика OOM), 7.6 (memory series), 7.3 (Compose
concurrency/cancellation/timeout, затем recovery, затем offline/isolation), 7.2
(итоговый live MVP run с отдельным quality review), 7.4 (итоговая сверка). Порядок
номеров сохранён для ссылок на исторические результаты, а не задаёт очередность.

Прежний global OOM подтверждён уже собранными результатами в
`docs/grounded-chat-api-server-acceptance.md`: разделы «Установлен global OOM хоста»,
«q01 после recovery и второй правки prompt: оба режима завершены» и «Readiness и
baseline свежей LLM подтверждены», 2026-10-22. Kernel: global_oom/CONSTRAINT_NONE,
victim llama-server PID 3709157, anon-rss=10472084 kB; Docker OOMKilled/exit=137,
PID=0, memory/swap limits=0. Подтверждены stop прежнего процесса, start LLM,
restart app, health=ok и baseline LLM 5.192 GiB / app 71.98 MiB / host available
8.1 GiB, а затем успешный транспорт q01. Эти диагностика и recovery не повторяются
в 7.5. Задача сводит имеющиеся evidence и timestamps; запрос оператору допускается
лишь для конкретно названного недостающего факта с объяснением, почему имеющихся
данных недостаточно. Пробел — memory telemetry всей серии и пиков под нагрузкой;
он относится к 7.6, не к повторному сбору прежних kernel/inspect/health результатов.
Свежий pre-run baseline в 7.6 нужен для нового интервала измерений, а не для
ретроспективного подтверждения уже принятого recovery.

Причина большого anon-rss не установлена: не объявлять leak, KV/cache/graph growth
без measurements. Не требуется заранее доказать конкретный механизм
allocation; неразобранный продолжающийся рост, нехватка headroom или повторный OOM
блокируют стабильность. Нельзя считать единичный recovery доказательством серии
или Compose acceptance. Не менять модель, flags, ресурсы хоста, swap и сторонние
сервисы как неявную часть диагностики; необходимое изменение вынести владельцу.

Предлагаемый ограниченный протокол для review:

1. До запуска зафиксировать identity модели/image/settings/messages и read-only
   индекса, отсутствие uncertain generation, readiness и baseline app/LLM/host RAM/
   swap. Фиксированная последовательность 20 end-to-end single-question HTTP chat
   запросов (одна позиция — один HTTP запрос, повторы преднамеренные):
   `q01, q02, q03, q05, q06, q07, q09, q11, q12, q13, q14, q15, q17, q19, q01, q02, q03, q05, q06, q19`.
   Все IDs проверены только по metadata `id/split/source_set`: tuning/live.
   Holdout, включая q18, в серии отсутствует. Вопросы передаются без изменений из
   frozen corpus; generation-only и дополнительные completions не добавляются.
   Повторный прогон за хорошим ответом, перестановки и замена cases по результатам
   запрещены; прерывание даёт incomplete run. Baseline/budget preflight не должен
   отправлять пробные completions; непроходящий прежние бюджеты case нельзя молча
   заменить. Искусственно увеличивать reserve/окно нельзя. Нет второго chat/harness
   traffic, HTTP requests не запускаются параллельно. Это нагрузка для измерения
   stability, не tuning ответов; safety/quality verdicts оцениваются отдельно.
2. Оператор записывает раз в секунду container memory app/LLM и временных harness
   containers (если они есть), host available RAM и swap; отмечает начало/конец
   каждого запроса, статус, counts/timings, post-response memory и OOM counters/
   process identity. Сохранить доступные cgroup peak counters с их областью учёта;
   максимум samples называть наблюдаемым пиком, не абсолютным пиком между samples.
   Baseline, transient peaks и post-run snapshots не смешивать.
3. Для этой серии stop threshold — host `/proc/meminfo:MemAvailable` ниже 2 GiB
   (2097152 KiB), новый OOM,
   завершение LLM либо transport failure/uncertain generation. Это предлагаемые
   параметры приёмки (20 запросов, интервал 1 s, порог 2 GiB), не новая runtime
   настройка. Порог консервативный, не гарантирует предотвращения OOM: давление
   других процессов и пики между samples могут опередить реакцию оператора.
   Если MemAvailable уже ниже порога до серии, запросы не отправляются.
   При stop оператор прекращает подачу запросов, при memory pressure
   подтверждённо останавливает LLM и собирает diagnostics; Ctrl+C клиента не является
   остановкой серверной генерации. Без recovery нет retry или следующего completion.
4. Pass: все 20 запросов завершены по API contract без непредусмотренных transport
   errors/OOM, host threshold соблюдён, наблюдения полны. Безопасный validation
   fallback учитывается отдельно и не является transport failure или quality pass.
   Оценить тренд всей серии: baseline, все 20 post-response samples, transient peaks,
   host MemAvailable/swap и повторные одинаковые cases в начале/конце. Не исключать
   первые запросы или ограничиваться последними пятью. Ступенчатый/немонотонный
   рост может оставаться продолжающимся; локальное плато не доказывает устойчивость.
   Продолжающийся необъяснённый рост или недостаточный headroom оставляют gate
   открытым, даже если последние пять samples не растут строго монотонно. Частичный
   run, потеря telemetry или неразобранный тренд не засчитываются как pass; усреднение
   не должно скрывать пики/рост. При нарушении stop criteria серия прекращается.
   Это доказательство только ограниченной серии, не отсутствия leak на любой нагрузке.

После memory gate выполнить Compose checks из §7: два одновременных запроса,
cancellation с поздним полным ответом и с uncertain timeout, контролируемый обрыв/
HTTP timeout при продолжающейся генерации без смены LLM flags. **До операторского
timeout испытания** требуется отдельная конкретная воспроизводимая процедура fault
injection: точные команды, test-only transport boundary, request timeline,
preconditions/cleanup и наблюдаемые критерии 504/503/отсутствия следующего completion.
Она должна сохранять production flags/settings/timeout и позволять доказать,
что fault произошёл после возможной отправки completion и не подтверждает его
завершения. Нужен счётчик/trace именно upstream completions; клиентский timeout
сам по себе не доказывает timeout приложения или работу generation_uncertain.
После fault и generation_uncertain процедура допускает только проверочные HTTP
chat запросы к заблокированному app с ожидаемой 503, но исключает отправку ими
следующего upstream completion, прямые LLM probes/completions, retry, снятие slot
и restart только app. До этих probes требуется определённый способ наблюдения
блокировки и upstream count; иначе испытание не начинается. Затем только
подтверждённая остановка прежней LLM, её запуск и restart app разрешают новый
completion. Если безопасная воспроизводимая процедура не подготовлена/не проверяема,
timeout gate остаётся открытым; это planning prerequisite, а не готовая команда
для запуска. Затем
подтвердить recovery и успешный новый chat, offline/app-only/isolation и неизменность
SQLite. Health должен оставаться отзывчивым, но не считается доказательством
прекращения генерации. При отсутствии live доступа эти gates остаются открытыми.

## Risks / Trade-offs

- [Валидная citation не доказывает entailment; команда может оказаться вне fences] → строгие правила, exact-block checks и ручной review corpus; не заявлять автоматическую гарантию всех фактов.
- [Малая Qwen нарушает JSON/prompt/injection rules] → консервативный fallback и реальные server checks; нарушения validators/безопасности блокируют MVP, semantic quality failures остаются открытыми post-MVP дефектами, без verifier model или незаметной смены модели.
- [Повторный global OOM или рост памяти] → ограниченная наблюдаемая серия и stop criteria §9; отсутствие измерений не заменять предположением о стабильности. Новый resource/runtime вариант требует отдельного решения владельца.
- [Token endpoints/chat template отличаются между llama.cpp builds] → compatibility smoke с полным шаблоном на установленном image и явная техническая ошибка при несовместимости, без character heuristic.
- [Очередь CPU повышает latency] → один worker, отдельные wait/generation timings, 300s transport timeout и документированный длительный client timeout; не увеличивать parallelism без нового решения.
- [Полные исходные ranges в sources увеличивают response] → top-k и context budget ограничивают объём; точность provenance важнее сокращения цитат моделью.
- [Страница по URL изменилась после reindex] → docs поясняют snapshot semantics: quote относится к index generation, ссылка открывает текущую Wiki.js страницу.
- [Основная hybrid spec содержит старый MVP quality gate] → раскрытое расхождение разрешается приоритетом SPEC.md в этом plan; исторические результаты и ranking не меняются.

## Migration Plan

1. Исходный этап (выполнен, результаты сохранены): ранний live gate 2.1 на закреплённом runtime до реализации зависимого LLM client/token counter, затем route/service и профильные checks. SQLite schema и существующий индекс сохраняются; повторять gate без изменения identity не требуется.
2. Исходный этап (выполнен): app settings и Compose environment для context/timeout, документация запросов/ошибок и `.env.example`. Эти настройки не изменяются в пересмотре; README/ROADMAP не менять.
3. Продолжить с принятым gate 7.1 без смены messages/runtime: диагностика OOM → memory series → Compose concurrency/cancellation/timeout → ручной recovery → offline/app-only/isolation/SQLite → итоговый live MVP run. Semantic quality оформить отдельно как post-MVP, не переписывая прежние failures. `parts` не реализовывать. При необходимости менять runtime сначала получить отдельное решение владельца.
4. При rollback вернуть предыдущий app image/code и environment; индекс не мигрировал и остаётся совместимым. Внешних записей, которые нужно откатывать, нет.
