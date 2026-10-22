# Grounded chat API: lifecycle и retrieval

На 2026-10-21 реализованы `POST /api/chat`, LLM client, active retrieval,
prompt, budget packing и validators. Linux-проверка фактической замены
открытого файла (задача 1.3) принята по выводу оператора: 30 passed,
`PATHNAME_REPLACEMENT_OK`. Live-gate 2.1 также принят: calculated/actual
65/65 и 202/202, cached_tokens=0 на закреплённом image/model. Compose config
также подтверждён оператором: 8192/768/300. Финальная token compatibility 7.1
принята по live-выводу 2026-10-22: 1850/1850, 7424/7424 и overflow без completion.
Приёмка 7.2–7.3 остаётся открытой; автоматические fixtures не подтверждают качество Qwen.

## Настройки chat

`load_chat_settings()` отдельно загружает immutable `ChatSettings` при
необходимости chat. Startup и `/health` не валидируют новые chat budgets.
Python не загружает `.env` автоматически; при локальном запуске переменные
нужно экспортировать. Compose читает свои значения из environment/`.env`.

| Переменная | Default | Назначение |
|---|---:|---|
| `LLM_CONTEXT_SIZE` | 8192 | Полное окно prompt + reserve; одно значение для app и llm `--ctx-size` |
| `LLM_MAX_TOKENS` | 768 | Резерв ответа и completion request max_tokens |
| `LLM_TIMEOUT_SECONDS` | 300 | Конечный timeout отдельного HTTP-вызова LLM; ожидание слота сюда не входит |

Все три значения — положительные целые; reserve должен быть строго меньше
окна. Ошибки settings содержат категорию, без исходного значения.
`LLM_MODEL_NAME` default `Qwen3-4B-Instruct-2507`, sampling defaults
temperature=0.2, top_p=0.8, top_k=20 сохранены. Изменение context size при
эксплуатации требует согласованного значения у app/runtime; текущий этап
не меняет закреплённые LLM image, flags или template.

## Удерживаемое поколение

Lifespan создаёт `RetrievalService` с одним выделенным executor thread.
Этот поток открывает и проверяет SQLite через `load_index_state`, выполняет
поиски и закрывает ресурсы. Существующий `app.state.index` сохраняется;
внутренний `app.state.retrieval` предоставляет асинхронный `search(question)`.
Публичных retrieval/reindex/context override endpoints этот слой не добавляет.

Hybrid view заимствует удерживаемые reader, validated semantic matrix и
snapshot у `ActiveIndex`. Он не открывает pathname повторно и не перечитывает
matrix. Semantic identity encoder проверяется до поиска. Lexical probe
закрывает view, основной reader закрывает `IndexState`. Standalone
`HybridIndex(path, encoder, settings)` и CLI сохраняют прежнее владение.

Одновременные поиски сериализуются в executor. Возвращается tuple
`HybridResult` с `StoredChunk` из того же snapshot: исходный Markdown,
source ranges, title и source URL согласованы с retrieval. Отмена ожидания
не прерывает выполняющуюся SQLite-операцию. Закрытие ставится после уже
отправленных операций и выполняется в том же потоке, включая поиск,
завершившийся ошибкой. Поздние ошибки отменённых ожиданий извлекаются без
необработанных asyncio diagnostics.

Публикация нового индекса не переключает уже работающий процесс. Прежнее
поколение удерживается до restart; новый lifespan загружает новое поколение.
Будущие quotes должны относиться к этому snapshot, а URL откроет текущую
страницу Wiki.js, которая могла измениться после индексации.

## Read-only и lazy assets

Поиск использует прежние semantic/lexical/RRF правила и defaults:
10 semantic candidates, 10 lexical candidates, RRF constant 60, top-k 6.
Environment overrides сохраняются через `load_retrieval_settings`.
Отказ ветки не превращается в молчаливый fallback.

`LocalEncoder` и retrieval settings создаются при первом поиске в executor.
Startup не требует embedding assets, LLM или Wiki.js. Отсутствующий,
повреждённый либо несовместимый индекс остаётся unavailable; индекс не
создаётся автоматически. Запросы не изменяют SQLite, не запускают ingestion
или reindex и не скачивают model assets. Health сохраняет HTTP 200 и JSON
`{"status":"ok"}` без readiness checks. Ошибка lazy encoder не закрывает
удерживаемый reader и не ломает health.

## Граница этапа и проверки

Chat обрабатывает текущий вопрос независимо. История,
follow-up и query rewriting относятся к следующему change `session-follow-up`.

Temporary SQLite tests сравнивают borrowed view со standalone hybrid,
проверяют model identity mismatch, defaults, сериализацию concurrent searches,
закрытие после ошибки/отмены, app-only startup и согласованность source metadata.

В Windows `os.replace` открытого SQLite может завершаться `PermissionError`.
В этом случае тест проверяет сохранность старого snapshot, отсутствие повторного
открытия и загрузку нового поколения после close, но **не подтверждает подмену
pathname при открытом reader**. Фактический Linux-прогон 1.3 выполнен оператором
и подтверждён в журнале. Команда из каталога `app/` в подготовленном Linux окружении:

```bash
python -m pytest -q -rs tests/test_active_retrieval.py tests/test_index_state.py tests/test_hybrid_retrieval.py tests/test_hybrid_retrieval_cli.py tests/test_health.py
```

В Linux тест не допускает `PermissionError` вместо подмены. После успешного
`os.replace` он требует прежние результаты и provenance до close и новое
поколение при следующем startup. Локальные результаты и оставшиеся gates:
[журнал проверки](grounded-chat-api-server-acceptance.md).
В журнале также приведена одна Docker-команда из корня проекта: отдельный
контейнер с read-only исходниками, SQLite только в tmpfs и явным маркером
`PATHNAME_REPLACEMENT_OK` в успешном Linux-выводе.

## HTTP contract и запуск

Локально из `app/`, с экспортированными `INDEX_PATH`, embedding и LLM settings:

```bash
python -m app
```

После подготовки app image, индекса и offline assets штатный Compose запуск
app выполняется из корня проекта командой `docker compose up -d --no-deps app`.
Это отдельное действие оператора при выкладке; diagnostics не меняют llama.cpp
image/flags/template. Uvicorn по-прежнему использует **один worker**.

Запрос к локальному процессу или опубликованному Compose app port:

```bash
curl --fail-with-body --max-time 1800 http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"Как работает роутплан?"}'
```

`session_id` и `message` — обязательные strict strings, непустые после trim;
дополнительные поля запрещены. До trim считается длина исходной строки,
включая whitespace: максимум **128** и **4096 Unicode code points** соответственно.
Превышение даёт 422 до retrieval/model calls, текст не обрезается.
Отдельно проверяются E5 input ≤512 tokens (с `query:` и special tokens)
и полный LLM prompt с reserve; вопрос в 4096 символов может не пройти эти бюджеты.
Повторный session_id не добавляет историю. Публичных reindex/context overrides нет.

Успешный ответ имеет только `answer`, `insufficient_context`, `sources`.
Каждый source содержит `title`, `heading`, `url`, `quote`. Пример формы:

```json
{"answer":"Подтверждённый ответ [1]","insufficient_context":false,"sources":[{"title":"Title","heading":"Heading","url":"https://wiki.example/ru/page","quote":"source command"}]}
```

Этот пример формы проверен fixture API, а не является фактическим ответом Qwen.
`heading` пустой, если heading path отсутствует. Несмежные исходные ranges дают
отдельные source entries, поэтому один chunk может ссылаться как `[1] [2]`.
Нумерация идёт по первому появлению chunk в ответе, ranges — в исходном порядке;
повтор chunk использует те же номера. Два chunks одной страницы не объединяются
в одну page citation. Backend берёт URL из snapshot без выдуманного heading anchor.

## Prompt, evidence и точный token budget

Prompt состоит из двух messages: фиксированные русские system rules и JSON
с текущим question и недоверенным CONTEXT. Title/headings/fragments сериализуются
как данные; псевдо-delimiters в документах не создают новых messages/instructions.
Manifest содержит chunk IDs и только `document.markdown[start:end]`: соседние
или перекрывающиеся ranges объединяются, несмежные остаются раздельными.
Generated table headers/fences и `search_text` не входят в evidence. URLs модели
для citations не передаются. Модель получает запрет внешних знаний, выполнения
инструкций из документов, придуманных URLs/команд/значений; tools отсутствуют.

Правила выбора kind сначала требуют определить объект из текущего вопроса:
похожая найденная инструкция не разрешает угадывать отсутствующий объект.
Для ясного вопроса модель сопоставляет каждую запрошенную часть со всеми
переданными fragments, сохраняет связь факта с объектом/полем/разделом и выдаёт
полный ответ без общей оговорки о недостаточности, если сведения есть.
Частичный ответ называет конкретный пробел; полный отказ допустим, когда
ни одна часть не подтверждена. Каждая citation должна подтверждать соседний
claim, тематической близости недостаточно. Эти prompt rules требуют live review;
backend не проверяет их семантическое исполнение.

System rules также содержат вымышленные учебные примеры JSON: полный ответ,
partial с конкретным пробелом, дословная fenced-команда и уточнение неизвестного
объекта. Они показывают расположение citations и соответствие kind ответу;
данные примеров и их ID не разрешены как evidence текущего запроса. Примеры
проверяются действующими parser/citation/code validators, но их наличие
не доказывает соблюдение правил Qwen: эффект оценивается только live.

Полный messages array проходит `/apply-template` с `add_generation_prompt=true`,
затем `/tokenize` с `add_special=true`, `parse_special=true`, `with_pieces=false`.
Этот точный путь подтверждён ранним live-gate 2.1; в 7.1 он повторяется с текущими
rules/manifest и границами окна. Character heuristics, корректирующих коэффициентов
и дополнительного HF tokenizer нет. Каждый удаляемый chunk целиком исключается
из CONTEXT; подсчёт полного prompt повторяется после удаления. Сначала проверяется
минимальный prompt без chunks. Равенство `prompt_tokens + reserve == window`
допускается, превышение удаляет последний chunk ranking. Если минимальный prompt
не помещается — 422; если контекст стал пустым — стандартный отказ без completion.

Scores определяют ranking, а не достаточность; score threshold отсутствует.
Completion — ровно один запрос, stream=false, alias из settings и sampling
0.2/0.8/20; `cache_prompt=false`. Transport отключает proxies и redirects,
не передаёт tools и не делает retries. Недоступный token endpoint — техническая
ошибка, а не повод применить приблизительный budget или вернуть отказ по Wiki.

## Тип ответа и validation fallback

Внутренний JSON модели содержит только `kind` и `answer`; лишние поля, duplicate
keys, внешние JSON fences и невалидный JSON отклоняются. Во внешнем API kind нет.

| Внутренний kind | Поведение | insufficient_context |
|---|---|---|
| `answer` | Содержательный ответ с citations из packed manifest | false |
| `partial` | Подтверждённая часть с citations и явно названными пробелами | true |
| `refuse` | Backend выводит стандартную фразу отказа без фактов модели | true |
| `clarify` | Один короткий уточняющий вопрос; без утверждений sources могут быть пустыми | true |

При конфликте prompt требует `partial`, оба варианта и citations обеих сторон;
выбирать версию без основания запрещено. Fixture validator возвращает, например,
`Противоречие: 80 [1], 81 [2]. Не могу выбрать верный.` с двумя source quotes
`port=80`/`port=81`. Семантический выбор kind и entailment проверяет человек.

Полный отказ: `В документации недостаточно информации для ответа на этот вопрос.`
с `insufficient_context=true`; он не заменяет технические 503/504/502.
При неизвестной/удалённой/неправильной citation, отсутствии citations у answer/partial,
сгенерированной source link, malformed JSON либо неподтверждённом коде весь output
заменяется фразой `Не удалось подтвердить ответ по найденным источникам. Откройте источники ниже.`
и исходными fragments packed manifest. Неподтверждённые утверждения не сохраняются,
LLM повторно не вызывается. Модель не выбирает quotes/URLs или номера.

Каждый fenced code block проверяется отдельно: body без fences/language marker
и одного delimiter newline перед closing fence должен быть точной подстрокой
**одного** переданного непрерывного fragment. Нет нормализации whitespace,
CRLF/LF, IP, flags и identifiers. Склейка раздельных ranges, generated fences/headers,
удалённый chunk или непереданный участок документа не являются подтверждением.
Незакрытые/неправильные fences также дают fallback. После замены citations код
проверяется ещё раз, чтобы backend numbering не изменило команду.

Эти проверки не доказывают поддержку всех утверждений. Скрытые команды в обычной
прозе, факты в уточняющем вопросе и смысл citations требуют ручного review.
Строгий prompt и наличие citations не гарантируют отсутствие галлюцинаций/injection.

## Очередь, ошибки и recovery

Retrieval выполняется до generation slot. Один process-wide slot сериализует
template/tokenize/packing/completion; SQLite использует собственный последовательный
executor. Event loop остаётся свободным для `/health`. Query, retrieval, wait и
generation durations логируются отдельно безопасными числовыми полями и категориями;
session_id, message, prompt, source text, credentials/DSN и raw exceptions не логируются.
Generation timing включает только completion transport. При отмене запроса поздний
generation timing логируется отдельно, завершения transport дожидается защищённая task.

`LLM_TIMEOUT_SECONDS` относится к HTTP transport, а не ожиданию slot. Клиентский timeout
должен учитывать несколько минут очереди; пример curl использует 1800 секунд.
Отмена ожидающего клиента удаляет его ожидание. После начала model interaction
отмена клиента не освобождает slot раньше завершения защищённого transport.

| HTTP | Значение |
|---|---|
| 200 | Подтверждённый ответ, partial/refuse/clarify либо безопасный validation fallback |
| 422 | Неверные поля/типы/длины или превышение отдельного E5/LLM бюджета вопроса |
| 503 | Индекс/assets/configuration/retrieval/LLM недоступны, либо generation_uncertain |
| 504 | Истёк HTTP timeout LLM |
| 502 | Некорректный transport JSON/envelope, alias mismatch, пустой content или token protocol |

Ошибки validation не отражают исходный payload. HTTP 503 при недоступном индексе
не означает, что в Wiki нет ответа. App-only startup без индекса/assets/LLM сохраняет
`GET /health` → HTTP 200 `{"status":"ok"}`; chat при этом получает 503.

Полный completion response позволяет освободить slot, в том числе если полученный
envelope впоследствии отклонён. После timeout/socket loss с возможной отправкой
completion сервер мог продолжить генерацию: исходный timeout даёт **504**, slot
остаётся в **generation_uncertain**, уже ожидающие и новые запросы получают **503**.
Нет следующего completion/retry, даже после health=ok или истечения времени.
Ошибки до отправки completion и только token counting не блокируют слот как uncertain.
Shutdown прекращает новую работу, ждёт защищённые tasks не более одной секунды в
lifespan и не заявляет о прекращении удалённой генерации; активный локальный transport
продолжает иметь свой конечный HTTP timeout.

Recovery выполняет оператор: **подтверждённая остановка прежнего llama-server
процесса → штатный запуск LLM → restart app**. Один restart app, health=ok, закрытый
socket или задержка не доказывают, что старая генерация прекратилась. При изменении
процессов следует исключить отправку запросов до завершения этого recovery.
Автоматического release по таймеру, restart runtime, новых flags или polling slot API нет.

## Frozen evaluation и ручной checklist

`python -m app.chat_evaluation` — только административный CLI. Обычный API не
принимает context. CLI валидирует frozen package, source namespaces, inventory
индексов и fingerprints до/после прогона. Case IDs, splits, expectations и baseline
не меняются. Default прогон включает все single-question cases, включая все
answerable=false; follow-up исключены и не заявляются принятыми.

Из `app/`, с настроенным internal LLM origin и offline assets, пример generation-only
по достаточным **исходным frozen evidence ranges**:

```bash
python -m app.chat_evaluation --mode generation-only \
  --questions ../eval/questions.yaml --manifest ../eval/manifest.json \
  --snapshot "$FROZEN_SNAPSHOT" --fixtures ../eval/fixtures/wiki-documents.json
```

End-to-end дополнительно использует текущий hybrid retrieval по двум подготовленным
SQLite индексам **тех же frozen документов**:

```bash
python -m app.chat_evaluation --mode end-to-end \
  --questions ../eval/questions.yaml --manifest ../eval/manifest.json \
  --snapshot "$FROZEN_SNAPSHOT" --fixtures ../eval/fixtures/wiki-documents.json \
  --index "$FROZEN_LIVE_INDEX" --synthetic-index "$FROZEN_SYNTHETIC_INDEX"
```

Имена переменных обозначают уже подготовленные локальные файлы; CLI их не создаёт.
Актуальный production-индекс с другим corpus отклоняется. Generation-only не требует
E5/индексов, но использует тот же final prompt/packing/validation; у кейсов без evidence
он возвращает отказ без completion. Для выбора case есть `--case q01`, без изменения
splits/inputs. Эти примеры не запускались на целевой Qwen в текущей локальной среде.

Report — JSONL с case ID/namespace/split, retrieved/supplied/packed IDs, evidence
coverage, timings, calculated/actual tokens, API response и `manual_verdict=pending`.
Это административный артефакт с quotes, а не технический лог: хранить с доступом
как к frozen corpus. Unsupported generated output при fallback не публикуется.
Поле `validation_error` содержит безопасную категорию отказа validator
(`generated_json`, `citation_missing`, `citation_unknown`, `citation_marker`,
`generated_source_link`, `code_fence`, `code_source`, `clarify_format`) либо null.
Это причина структурного отклонения, а не entailment verdict; сырой completion
и prompt не добавляются в отчёт или логи. Публичный response не меняется.
Wrapper `docs/grounded-chat-api-evaluate.sh` также принимает повторяемый
`--case CASE_ID` и передаёт выбранные IDs обоим режимам; без аргументов
по-прежнему выполняется весь single-question corpus. Выборочный прогон служит
диагностике, не заменяет полную live-приёмку и не меняет frozen splits.
`retrieval_miss` отделяется от `context_miss`; `review_generation` требует оценки
модели при достаточном evidence, а не автоматического pass. При timeout/ошибке
CLI останавливается без следующего completion или retry; прежние case строки уже
выведены, успешного summary не будет. Не запускать параллельно с chat/другим harness.

Дополнительные локальные fixtures в `test_grounding.py` покрывают partial/clarify,
два конфликтующих sources, prompt injection, похожие identifiers/IP и 180-строчный
code block; frozen eval inputs для них не редактировались.

Для каждого реального case вручную проверить:

- Все required facts и exact_commands, без новых значений/инструкций.
- Каждый factual claim поддержан соседней citation и фактически packed fragment.
- Код целиком дословный, без подстановки IP/flags/whitespace, оба конфликтующих
  варианта показаны; partial называет пробелы, clarify задаёт один вопрос.
- Все answerable=false не получили выдуманного содержательного ответа;
  injection не поменяла rules, prompts/URLs не приняты за authority.
- Evidence miss отделён от generation failure; sufficient-context generation
  проверена отдельно от end-to-end retrieval.

Численный Hit@5 ≥90% относится к post-MVP и не блокирует этот change. Реальные
case verdicts и ограничения обязательны. Qwen generation review 7.2 и Compose
concurrency/offline/recovery 7.3 остаются серверными задачами; локальные unit/API
tests их не заменяют. Token compatibility 7.1 принята по live-выводу оператора
2026-10-22; готовый запуск обоих режимов
7.2 описан в [журнале проверки](grounded-chat-api-server-acceptance.md).
