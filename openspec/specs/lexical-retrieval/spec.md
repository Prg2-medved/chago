# lexical-retrieval Specification

## Purpose
Находить chunks локальной документации по ключевым словам и явно заданным техническим literals, сохраняя проверяемую связь результатов с исходным Markdown и совместимость существующих SQLite snapshots.

## Requirements

### Requirement: Complete lexical snapshot publication
Система SHALL дополнять проверенный semantic SQLite snapshot versioned lexical extension в отдельном output файле без повторного embedding inference, model assets, Wiki.js или сетевых обращений. Extension SHALL использовать FTS5 со стандартным `unicode61` и индексировать title, heading path и search_text каждого chunk ровно один раз. Documents, chunks, IDs, provenance, embedding bytes и semantic metadata SHALL сохраняться без изменений; base storage и semantic versions SHALL оставаться прежними. Metadata SHALL фиксировать lexical format/input/query/literal policy versions, tokenizer options, counts и SQLite build version. Полный rebuild SHALL заменять inventory, включая удалённые chunks. Пустой inventory SHALL давать валидный extension с нулём записей. Output SHALL NOT совпадать с input, включая aliases, или указывать на model assets. Публикация SHALL происходить только после закрытия записи, base/semantic/lexical validation, проверки FTS postings и повторного чтения; любая ошибка SHALL сохранять input и прежний output.

#### Scenario: Extend and reopen a semantic snapshot
- **WHEN** build получает валидный semantic snapshot и отдельный output
- **THEN** после повторного открытия всем chunks соответствует lexical content, а documents, provenance, embedding bytes и semantic metadata равны input; inference и сетевые обращения не выполнялись

#### Scenario: Failed build or protected output
- **WHEN** отсутствует FTS5, повреждён semantic input, output совпадает с input/assets либо запись/validation/publication завершается ошибкой
- **THEN** команда возвращает ненулевой код с безопасной категорией и не меняет input, assets или прежний output

#### Scenario: Removed and empty inventory
- **WHEN** build использует новый snapshot без части прежних chunks или с нулём chunks
- **THEN** output содержит только новое inventory и точное соответствующее число lexical записей, без stale postings

### Requirement: Read-only lexical validation and compatibility
Lexical query SHALL открывать существующий snapshot read-only без создания отсутствующего файла, изменения данных или автоматического rebuild. До поиска SHALL проверяться base storage/provenance, поддерживаемые lexical versions/options, точное соответствие lexical rows исходным chunks и согласованность postings. Missing, extra, duplicate или изменённые записи, повреждённые postings и неподдерживаемая lexical policy SHALL давать контролируемую ошибку с необходимостью rebuild. Lexical query SHALL работать без embedding inference, model assets и импорта тяжёлых embedding libraries. Base storage reader и pure semantic query SHALL продолжать читать совместимый расширенный файл по своим прежним контрактам и SHALL NOT заявлять валидность lexical extension. Старый semantic snapshot SHALL оставаться пригодным для pure semantic query; lexical/hybrid query SHALL отклонять файл без lexical extension. HTTP startup/health SHALL оставаться независимыми от индекса и FTS5.

#### Scenario: Lexical query without embedding runtime
- **WHEN** совместимый расширенный файл доступен, а model assets и импорты embedding libraries недоступны
- **THEN** lexical query возвращает ranked chunks без inference и изменения файла

#### Scenario: Content or postings corruption
- **WHEN** lexical content отличается от title/headings/search_text chunk, есть лишний/недостающий ID либо postings повреждены
- **THEN** query отклоняет snapshot до выдачи результатов без ремонта или записи в файл

#### Scenario: Internally consistent stale content
- **WHEN** FTS postings согласованы с собственным content, но этот content отличается от validated chunks
- **THEN** snapshot отклоняется по отдельной сверке content независимо от успешной внутренней FTS integrity проверки, без изменения исходного файла

#### Scenario: Existing modes remain available
- **WHEN** base reader читает расширенный файл либо pure semantic query читает прежний semantic-only файл
- **THEN** прежнее поведение сохраняется; отсутствие lexical extension влияет только на lexical/hybrid режимы

### Requirement: Safe keyword queries and deterministic BM25 ranking
Система SHALL принимать непустой вопрос и положительное целое k с lexical default k=10; неверные типы, whitespace-only вопрос и invalid k SHALL отклоняться явно. Пользовательский текст SHALL преобразовываться стандартным `unicode61` в уникальные экранированные термы, объединённые OR; исходный вопрос SHALL NOT исполняться как SQL или готовое `MATCH` expression. Пользовательские кавычки, operators, column filters, punctuation и скобки SHALL оставаться текстовыми данными. Без exact literal priority кандидаты SHALL ранжироваться по BM25 с меньшим значением первым и по chunk ID по возрастанию при равенстве. k выше числа кандидатов SHALL возвращать всех кандидатов; пустой inventory, отсутствие совпадений или отсутствие searchable terms/literals SHALL возвращать пустой список после validation. Морфологическое расширение, synonyms и query rewriting SHALL NOT выполняться.

#### Scenario: Russian keywords and punctuation
- **WHEN** вопрос содержит русский текст, mixed-case identifiers и пунктуацию
- **THEN** поиск использует стандартную `unicode61` tokenization и BM25 по title, heading path и search_text, с повторяемым порядком ties

#### Scenario: User supplied search operators
- **WHEN** вопрос содержит `OR`, `NOT`, `NEAR`, двойные кавычки, `title:`, звёздочки или SQL-подобный текст
- **THEN** эти данные не меняют синтаксис сформированного запроса и не вызывают SQL/FTS injection или неконтролируемую ошибку

#### Scenario: Empty candidates and invalid arguments
- **WHEN** валидный вопрос не даёт searchable terms/совпадений либо k превышает candidate count
- **THEN** выдаётся соответственно пустой список либо все кандидаты; invalid question/k даёт явную ошибку даже при пустом inventory

### Requirement: Exact technical literal priority
Система SHALL извлекать явно заданные IP-адреса, POSIX/Windows paths, технические identifiers с дефисом и непустые фрагменты в парных обратных кавычках, сохраняя регистр и символы. Quoted fragment SHALL проверяться как целое; его внутренние части SHALL NOT добавлять искусственные отдельные literal matches. Exact match SHALL требовать буквального вхождения в непрерывный исходный Markdown range, принадлежащий chunk; generated text и склейка несмежных source ranges SHALL NOT считаться таким совпадением. Для IP/path/identifier SHALL проверяться границы, исключающие совпадение с частью более длинного значения. Все chunks SHALL участвовать в literal check до lexical top-k truncation, включая chunks вне initial BM25 top-k. Кандидаты с хотя бы одним exact match SHALL стоять перед всеми остальными lexical-кандидатами; внутри этой группы SHALL сортироваться сначала по числу различных совпавших literals по убыванию, затем по BM25 при его наличии и по chunk ID при равенстве. Literal-only candidate SHALL быть допустим без BM25 score, с явным null для этого score. Выдача SHALL указывать source ranges буквальных совпадений без подмены ими semantic evidence.

#### Scenario: Similar IP paths and names
- **WHEN** вопрос явно указывает `10.20.30.40`, `/etc/route-plan/config.yaml` или `route-plan`, а chunks содержат точное значение и похожие `10.20.30.400`, `/etc/route-plan/config.yaml.bak`, `route-planner`
- **THEN** только точное значение с корректными границами получает literal priority; похожие значения могут участвовать как обычные keyword matches

#### Scenario: Original Markdown offsets and chunk boundaries
- **WHEN** chunk содержит generated prefix, Unicode/CRLF и source segment, заканчивающийся посреди более длинного identifier
- **THEN** literal evidence SHALL иметь original Markdown offsets в Unicode code points `[start, end)` и дословно совпадать с соответствующим source slice без смещения от generated text; границы typed literal SHALL проверяться по полному Markdown, а обрезанный prefix SHALL NOT получать exact priority

#### Scenario: Literal outside BM25 top ten
- **WHEN** chunk с точной командой в обратных кавычках находится ниже initial BM25 top 10 либо не имеет searchable terms
- **THEN** он включается в группу literal candidates до final lexical top-k и не теряется из-за предварительного BM25 truncation

#### Scenario: Generated and discontinuous text
- **WHEN** literal встречается только в generated segment либо получается лишь при объединении несмежных source ranges
- **THEN** chunk не получает exact literal priority за это вхождение

### Requirement: Lexical results and administrative commands
Lexical API/CLI SHALL предоставлять offline build и query, documented команды из app/ и Compose эквиваленты через существующий data mount. Ranked result SHALL включать rank начиная с 1, chunk ID, finite BM25 score либо null для literal-only candidate, literal match evidence и неизменные source identity, URL/title/headings, source ranges, source/generated segments и continuation metadata. Scores SHALL NOT трактоваться как вероятность ответа либо автоматическое решение об отказе. Build report SHALL включать counts и lexical identity без Markdown. Errors SHALL давать безопасную категорию без credentials, вопроса, исходного текста или необработанного backend exception. Query JSON SHALL содержать source/search text только как явный результат поиска. Этот режим SHALL NOT выполнять генерацию ответов, хранить историю или обращаться к LLM.

#### Scenario: Ranked provenance output
- **WHEN** query находит code/table continuation chunk
- **THEN** JSON сохраняет его provenance и различает source/generated segments; literal evidence ссылается на проверяемые исходные ranges

#### Scenario: Safe diagnostic
- **WHEN** CLI получает неверные аргументы либо DB/FTS operation завершается ошибкой
- **THEN** exit code ненулевой, диагностика содержит только безопасную категорию, а snapshots остаются неизменными
