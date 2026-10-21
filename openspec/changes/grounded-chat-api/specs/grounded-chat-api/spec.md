# Spec Delta

## Purpose

Предоставить минимальный локальный read-only RAG API, который отвечает по найденной документации, возвращает проверяемые источники и явно сообщает о недостатке сведений.

## ADDED Requirements

### Requirement: Stateless chat HTTP contract
Система SHALL предоставлять `POST /api/chat` с JSON-полями `session_id` и `message` — непустыми строками после проверки whitespace. Успешный HTTP 200 SHALL содержать `answer: string`, `insufficient_context: boolean`, `sources: array`; каждый source SHALL содержать `title`, `heading`, `url`, `quote` как строки. Ссылки `[1]`, `[2]` в answer SHALL соответствовать порядку sources. `heading` SHALL быть пустой строкой при отсутствии heading path. Этот этап SHALL обрабатывать каждый message независимо, без хранения истории, query rewriting или дополнительных поисков по предыдущим вопросам; `session_id` принимается для совместимости следующего этапа. Неверный тип, отсутствующие обязательные поля, пустой message/session_id и превышение бюджета вопроса SHALL давать HTTP 422 с безопасным сообщением без эха пользовательского ввода.

Длина исходной декодированной строки до trim SHALL быть не более 128 Unicode code points для `session_id` и 4096 для `message`, включая whitespace. Превышение SHALL давать безопасную HTTP 422 до retrieval и model calls, без обрезания значения. Лимиты длины SHALL NOT заменять отдельные E5/LLM token budgets.

#### Scenario: Valid request
- **WHEN** клиент передаёт непустые `session_id` и `message`, а все необходимые компоненты доступны
- **THEN** API возвращает HTTP 200 с полями answer, insufficient_context и sources в установленном формате

#### Scenario: Reused session identifier
- **WHEN** клиент отправляет второй вопрос с тем же session_id
- **THEN** retrieval и prompt используют только текущий вопрос, без предыдущего ответа или истории

#### Scenario: Invalid request
- **WHEN** обязательное поле отсутствует, имеет неверный тип или содержит только whitespace
- **THEN** API возвращает HTTP 422 без inference и без отражения исходного payload в ошибке

#### Scenario: Input length limits
- **WHEN** session_id имеет 128 либо 129 Unicode code points, или message имеет 4096 либо 4097, включая пробелы и Unicode
- **THEN** значение ровно на лимите проходит проверку длины с последующей обычной token validation; превышение отклоняется HTTP 422 до retrieval/model calls без echo input и без молчаливого сокращения

### Requirement: Read-only retrieval from the active generation
Каждый валидный chat request SHALL выполнять существующий hybrid retrieval по текущему удерживаемому активному поколению индекса, с E5 semantic search, lexical search и RRF. Defaults SHALL сохраняться: кандидаты 10/10, RRF k=60, final top-k=6; top-k SHALL настраиваться. Retrieval, переданные fragments и metadata ответа SHALL принадлежать одному поколению. Отказ ветки SHALL NOT давать молчаливый fallback. Scores SHALL NOT считаться доказательством достаточности контекста. Запрос SHALL NOT изменять индекс или обращаться к Wiki.js, запускать ingestion/reindex либо скачивать assets.

#### Scenario: Indexed code or table evidence
- **WHEN** hybrid search находит chunks кода либо таблицы
- **THEN** prompt получает соответствующие исходные fragments и chunk IDs, а ответ ссылается на metadata того же snapshot

#### Scenario: File replacement during a request
- **WHEN** путь индекса заменён после загрузки активного поколения
- **THEN** retrieval и sources текущего процесса остаются согласованными с удерживаемым поколением до штатного restart

#### Scenario: Valid empty index
- **WHEN** валидный вопрос прошёл штатную retrieval validation/inference, но совместимый индекс не содержит chunks
- **THEN** API возвращает стандартный отказ, insufficient_context=true и пустые sources без вызова генерации

### Requirement: Bounded local generation context
Система SHALL считать бюджет полного prompt токенизатором обслуживающей LLM с её chat template, включая system instructions, CONTEXT, вопрос, служебный формат и резерв ответа по `LLM_MAX_TOKENS` (default 768). Prompt и резерв SHALL помещаться в настроенный context window (default 8192), совпадающий с runtime. При переполнении SHALL удаляться наименее релевантные chunks целиком, без обрезания команд, вопроса или source fragments внутри chunk. Удалённые chunks SHALL NOT быть допустимыми citations. E5 query input SHALL соблюдать прежний лимит 512 tokens без truncation. Непомещающийся вопрос SHALL получать HTTP 422 с просьбой сократить его; если вопрос помещается, но ни один chunk не помещается, SHALL возвращаться отказ с недостатком контекста без генерации. Недоступность подсчёта LLM tokens SHALL быть технической ошибкой, без приблизительного character budget.

Совместимость точного token counting SHALL быть проверена live первой задачей блока 2 до реализации зависимых LLM client/token counter: calculated prompt tokens SHALL точно совпадать с фактическим `usage.prompt_tokens` completion для одинаковых messages на закреплённом image/model, с учётом chat template, generation prefix и special tokens. Отсутствие usage, несовместимость endpoints или несовпадение counts SHALL блокировать зависимую реализацию до согласования точного пути, без смены runtime и приблизительных поправок. Финальная приёмка SHALL повторять проверку на окончательном prompt.

#### Scenario: Early live token accounting compatibility
- **WHEN** на закреплённом llama.cpp image сравниваются короткий русский prompt и prompt с несколькими CONTEXT fragments, code/Unicode и служебным форматом
- **THEN** calculated counts точно равны `usage.prompt_tokens` для каждого случая; image/model identity, параметры и пары counts сохранены в отчёте, а mismatch/отсутствие live-доступа оставляет раннюю задачу невыполненной и зависимые задачи заблокированными

#### Scenario: Prompt at the context boundary
- **WHEN** полный шаблонизированный prompt вместе с резервом ответа равен лимиту либо превышает его
- **THEN** первый вариант допустим; во втором удаляются chunks с конца ranking до соблюдения лимита

#### Scenario: Removed citation
- **WHEN** модель ссылается на chunk, удалённый при budget packing
- **THEN** backend отклоняет сгенерированные утверждения как неподтверждённые

#### Scenario: Overlong question
- **WHEN** вопрос превышает E5 limit либо не помещается в LLM window даже без CONTEXT с обязательным резервом
- **THEN** API возвращает HTTP 422, не обрезая вопрос и не отправляя генерацию

### Requirement: Grounded Russian answers and insufficiency
LLM SHALL получать строгие правила: факты только из CONTEXT, русский язык ответа, точное сохранение identifiers, параметров, путей и команд, запрет дополнения из собственных знаний. При достаточном контексте ответ SHALL быть кратким, содержать необходимые подтверждённые факты и citations. При полном отсутствии сведений SHALL использоваться фраза `В документации недостаточно информации для ответа на этот вопрос.`; при подтверждении только части SHALL выдаваться подтверждённая часть с явно указанными пробелами; при неоднозначности SHALL допускаться один короткий уточняющий вопрос в том же вызове. Полный отказ, частичный ответ и уточнение SHALL иметь insufficient_context=true, полный ответ — false. Отказ/уточнение без фактических утверждений SHALL допускать пустые sources; содержательная часть частичного ответа SHALL иметь citations. Высокий retrieval score SHALL NOT разрешать выдумывание отсутствующих сведений.

#### Scenario: Sufficient evidence
- **WHEN** найденные и переданные источники содержат обязательные факты контрольного вопроса
- **THEN** ответ сообщает эти факты по-русски с подтверждающими citations, без добавленных значений или инструкций

#### Scenario: Unanswerable question despite nearby results
- **WHEN** retrieval вернул похожие chunks, но ответа на контрольный вопрос в них нет
- **THEN** API возвращает явный отказ с insufficient_context=true без ответа из знаний модели

#### Scenario: Partial and ambiguous evidence
- **WHEN** подтверждена только часть вопроса либо неясно, о каком объекте спрашивает пользователь
- **THEN** ответ обозначает недостающие сведения либо задаёт одно короткое уточнение, не выдумывая недостающую часть

### Requirement: Backend-owned citations and source fragments
LLM SHALL ссылаться только на chunk IDs, выданные в фактически переданном CONTEXT. Backend SHALL проверять каждый citation ID и формировать номера, title, heading path и URL из index metadata, а quote — дословно из исходных source ranges сохранённого Markdown соответствующего chunk. Generated fences/headers и `search_text` с generated segments SHALL NOT выдаваться за исходные цитаты. Несмежные ranges SHALL показываться отдельными source entries, без выдачи склейки за единый дословный fragment. Source URL SHALL NOT приниматься из output LLM. Если есть неизвестная/некорректная citation либо содержательный ответ не имеет citations, API SHALL возвращать HTTP 200, insufficient_context=true, сообщение о невозможности подтвердить ответ и доступные исходные fragments из переданного CONTEXT без сгенерированных утверждений. Backend SHALL NOT вызывать LLM повторно для исправления.

#### Scenario: Known citations
- **WHEN** модель сослалась на два допустимых chunk IDs
- **THEN** backend заменяет IDs стабильными номерами и возвращает реальные metadata и дословные quotes этих chunks

#### Scenario: Invented or missing citation
- **WHEN** содержательная генерация не имеет citations либо содержит неизвестный ID или подставленную моделью source link
- **THEN** сгенерированные утверждения не выдаются, возвращается безопасный ответ с доступными исходными fragments без повторной генерации

#### Scenario: Generated table header and disjoint ranges
- **WHEN** chunk содержит generated header либо несколько несмежных source ranges
- **THEN** sources содержат только отдельные дословные исходные ranges, без generated text и выдуманных heading anchors

### Requirement: Verbatim code and command validation
Команды SHALL приводиться только дословно в fenced code blocks, без сборки новых команд, подстановки значений и исправлений. Backend SHALL проверять содержимое каждого code block целиком как точную подстроку одного непрерывного исходного fragment, переданного LLM в текущем CONTEXT; language marker и внешние fence delimiters не являются содержимым. Кроме удаления одного служебного перевода строки перед закрывающей fence нормализация текста SHALL NOT выполняться. Совпадение с generated segments, удалённым chunk, непереданным участком документа либо склейкой раздельных fragments SHALL NOT считаться подтверждением. При несовпадении либо незакрытом code fence API SHALL скрывать сгенерированный ответ, предлагать открыть источники и возвращать insufficient_context=true с исходными fragments. Эта проверка SHALL NOT объявляться доказательством корректности остальных фактов.

#### Scenario: Exact source command
- **WHEN** fenced block дословно содержится в одном переданном source fragment
- **THEN** backend сохраняет блок без перевода или изменения команды

#### Scenario: Synthesized or altered command
- **WHEN** модель изменила IP, параметр, whitespace внутри команды или склеила части разных fragments
- **THEN** сгенерированная инструкция не показывается, ответ предлагает открыть исходные источники

### Requirement: Contradictions and untrusted documentation
Wiki text SHALL передаваться как явно обозначенные недоверенные данные с chunk IDs, отдельно от system instructions. Инструкции из документов SHALL NOT менять правила ответа. LLM SHALL NOT иметь tools, shell execution, SQL-доступ или полномочия изменять Wiki.js. Если переданные релевантные sources противоречат друг другу, ответ SHALL явно показывать расхождение, оба варианта с citations и SHALL NOT самостоятельно выбирать правильную версию без основания. Неразрешённое противоречие SHALL сопровождаться insufficient_context=true.

#### Scenario: Conflicting configuration values
- **WHEN** переданные sources дают разные значения одного параметра
- **THEN** ответ сообщает о противоречии и показывает оба варианта с исходными цитатами и ссылками

#### Scenario: Prompt injection in a retrieved page
- **WHEN** документ требует игнорировать system prompt, ответить без citations либо выполнить shell-команду
- **THEN** контрольный ответ сохраняет правила grounded generation, не выполняет действий и не принимает текст документа за system instruction

### Requirement: Serialized internal local runtime
Генерация SHALL выполняться только на локальной Qwen через внутренний llama.cpp endpoint, без внешних API и runtime downloads. Порт LLM SHALL оставаться неопубликованным на хосте. Приложение SHALL работать одним worker и обеспечивать максимум одну активную генерацию application-level semaphore/очередью; ожидающие запросы SHALL ждать, не порождать параллельную генерацию. HTTP transport SHALL иметь конечный timeout, отдельный от ожидания semaphore, и SHALL NOT повторять генерацию автоматически. Отмена клиента SHALL NOT освобождать слот раньше подтверждённого завершения/прекращения генерации на сервере. Полный completion response SHALL допускать release; завершение HTTP thread, закрытие socket, timeout, `/health: ok` или истечение фиксированной задержки SHALL NOT считаться подтверждением завершения серверной генерации.

После timeout/обрыва с возможной отправкой completion система SHALL удерживать logical generation slot/semaphore в состоянии неопределённого завершения и SHALL NOT отправлять новый completion. Исходный timeout SHALL давать 504, ожидающие и новые chat запросы SHALL получать безопасную 503 без бессрочного зависания. Без подтверждения завершения автоматического release SHALL NOT быть. В рамках этого этапа recovery SHALL быть ручным: подтверждённая остановка прежнего llama-server процесса, штатный запуск LLM и затем restart app; restart только app SHALL NOT считаться достаточным. Автоматический restart runtime, новые runtime flags и retry SHALL отсутствовать. Ошибки до отправки completion и ошибки только token counting SHALL NOT блокировать generation slot как неопределённый. Shutdown SHALL закрывать локальные ресурсы без бессрочного ожидания удалённой генерации и без заявления о её прекращении.

#### Scenario: Two simultaneous requests
- **WHEN** два chat запроса готовы к вызову LLM
- **THEN** второй ожидает завершения первого, число активных генераций не превышает одного, а wait duration измеряется отдельно

#### Scenario: Client cancellation
- **WHEN** клиент отключился во время работающего LLM transport
- **THEN** новая генерация не запускается параллельно с ещё выполняющимся вызовом

#### Scenario: HTTP timeout while the server keeps generating
- **WHEN** completion transport завершается timeout, а llama-server продолжает генерацию либо её завершение нельзя доказать
- **THEN** исходный запрос получает 504, semaphore остаётся зарезервированным, ожидающие и новые запросы получают 503 без отправки нового completion; health=ok и прошедшее время не освобождают слот

#### Scenario: Completion after client cancellation
- **WHEN** клиент отключился, но защищённый фоновый transport позднее получил полный completion response
- **THEN** слот освобождается только после этого ответа; если вместо ответа получен timeout/обрыв, сохраняется состояние неопределённого завершения

#### Scenario: Safe release and operational recovery
- **WHEN** ошибка произошла гарантированно до отправки completion либо оператор выполнил подтверждённую остановку старой LLM, запуск LLM и restart app
- **THEN** первый случай допускает обычный release без блокировки, второй восстанавливает chat; один restart app не выдаётся за подтверждённое завершение старой генерации

### Requirement: Technical errors and app-only compatibility
Отсутствующий/невалидный индекс, несовместимые или недоступные embedding assets, ошибки retrieval и недоступная LLM SHALL давать безопасную HTTP 503; timeout LLM SHALL давать HTTP 504; некорректный transport response LLM SHALL давать HTTP 502. Некорректный формат содержимого генерации SHALL обрабатываться как неподтверждённый ответ HTTP 200 с исходными fragments. Технические ошибки SHALL NOT представляться отказом по отсутствию сведений в Wiki.js. App-only startup и `GET /health` SHALL сохранять HTTP 200 и `{"status":"ok"}` без LLM/model readiness checks. Система SHALL логировать query, retrieval, LLM wait и generation durations и безопасные категории ошибок, без credentials/DSN, raw exceptions, полного prompt/документов, session_id или message.

#### Scenario: Missing index or model
- **WHEN** app запущен без готового индекса либо embedding assets
- **THEN** health работает по прежнему контракту, chat возвращает техническую HTTP 503 без создания индекса или загрузок

#### Scenario: LLM failures
- **WHEN** LLM недоступна, превышает timeout либо возвращает сломанный HTTP JSON/envelope
- **THEN** chat возвращает соответственно 503, 504 либо 502 с безопасным сообщением, без утверждения об отсутствии информации в документации

#### Scenario: Malformed generated content
- **WHEN** transport envelope валиден, но модель вернула непарсируемое содержимое вместо согласованного формата ответа
- **THEN** backend не показывает сырой output, возвращает неподтверждённый ответ с исходными fragments и не повторяет генерацию

### Requirement: Grounded answer acceptance evidence
Приёмка SHALL включать автоматические проверки API/validators и фактические ответы локальной целевой модели на single-question evaluation cases: обычный текст, identifiers, code, table, partial, clarify, contradictions, injection и все `answerable: false`. Проверяющий SHALL вручную оценить обязательные факты, соответствие citations утверждениям, дословность команд и отсутствие неподтверждённых сведений. Отчёт SHALL различать retrieved evidence misses и generation failures, сохранять настройки, fingerprints, case IDs, timings и ограничения без изменения frozen corpus, expectations, splits и исторических baseline. Follow-up acceptance SHALL оставаться следующему этапу. Достижение Hit@5 ≥90% SHALL NOT быть условием завершения этого change согласно SPEC.md §§12.5,27; отсутствие evidence SHALL вести к частичному ответу/уточнению/отказу.

#### Scenario: Live server review
- **WHEN** проводится приёмка на подготовленном локальном индексе и Qwen в Compose
- **THEN** отдельный отчёт фиксирует реальные ответы, evidence coverage, ручной verdict и ограничения; все unanswerable cases проходят без выдуманного содержательного ответа

#### Scenario: Evidence miss
- **WHEN** нужные факты есть в документации, но не попали в переданный CONTEXT
- **THEN** отсутствие полного ответа отражается как retrieval/context miss, а модель явно сообщает недостаток данных вместо дополнения из знаний
