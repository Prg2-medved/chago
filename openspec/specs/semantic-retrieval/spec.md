# semantic-retrieval Specification

## Purpose

Находить chunks локальной документации по смыслу русского вопроса с помощью предварительно установленной CPU embedding-модели, сохраняя проверяемую связь результатов с исходным Markdown.

## Requirements

### Requirement: Local verified embedding runtime
Система SHALL выполнять inference `intfloat/multilingual-e5-small` только на CPU из предварительно установленного локального каталога с закреплённой revision и проверенными hashes assets. Runtime SHALL NOT скачивать assets, использовать внешние embedding API или выполнять remote model code. Отсутствующие/повреждённые assets SHALL давать безопасную контролируемую ошибку. Конфигурация SHALL задавать локальный путь, model identity, batch size и CPU threads без необходимости изменения retrieval алгоритма; неподдерживаемая identity SHALL отклоняться явно. Embeddings SHALL быть конечными нормализованными векторами размерности 384; нулевые векторы SHALL отклоняться.

#### Scenario: Offline CPU inference
- **WHEN** локальные проверенные assets доступны, а сеть запрещена
- **THEN** embeddings русского текста вычисляются на CPU без сетевых обращений, имеют размерность 384 и единичную норму с float32 tolerance

#### Scenario: Minimal assets and safetensors-only loading
- **WHEN** доступны проверенные `model.safetensors`, `config.json`, `modules.json`, `sentence_bert_config.json`, `1_Pooling/config.json`, `tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`
- **THEN** runtime SHALL использовать fast tokenizer из `tokenizer.json` и явно требовать `use_safetensors=True`; `sentencepiece.bpe.model`, `pytorch_model.bin` и альтернативные exports SHALL NOT быть обязательными

#### Scenario: No pickle fallback
- **WHEN** safetensors отсутствует, повреждён или loader не может выполнить safetensors-only загрузку, даже при наличии `pytorch_model.bin`
- **THEN** runtime SHALL завершаться контролируемой ошибкой без pickle fallback, сетевых обращений и публикации индекса

#### Scenario: Missing or changed assets
- **WHEN** отсутствует обязательный файл модели либо его hash отличается от закреплённого
- **THEN** операция завершается контролируемой ошибкой без загрузки из сети и публикации индекса

### Requirement: Exact E5 inputs and budgets
Система SHALL использовать полный passage input существующего chunking: `passage: <title>\n<heading path joined by ' > '>\n<search_text>`, и `query: <question>` для вопроса. Полный input со special tokens SHALL проверяться совместимым локальным E5 tokenizer и содержать не более 512 tokens; truncation SHALL NOT использоваться. При построении SHALL проверяться tokenizer identity/fingerprint snapshot и фактические passage token counts. Пустой/whitespace-only вопрос и превышение query budget SHALL давать явную ошибку; вопрос SHALL NOT молча сокращаться.

#### Scenario: Passage matches chunking
- **WHEN** строятся embeddings chunk с title, вложенными headings и generated table/code segments
- **THEN** embedding получает то же поисковое представление, чей бюджет проверял chunking, без изменения исходных source ranges

#### Scenario: Boundary and overflow
- **WHEN** полный query либо passage содержит 512 tokens или 513 tokens
- **THEN** 512 принимается, 513 отклоняется до inference без обрезания

### Requirement: Complete semantic snapshot publication
Система SHALL строить semantic SQLite snapshot из проверенного storage-only snapshot, сохраняя дословные documents, chunks, IDs и provenance. Snapshot SHALL содержать по одному embedding на каждый chunk и metadata embedding format version, model ID/revision/assets fingerprint, tokenizer fingerprint, dimension, dtype, normalization и input format version. Embeddings и metadata SHALL находиться в том же SQLite файле, что документы/chunks. Новый snapshot SHALL полностью заменять inventory, включая удалённые chunks. Публикация SHALL происходить только после успешного inference, закрытия записи, integrity/foreign-key checks и повторного полного чтения. Ошибки SHALL сохранять исходный файл и прежний output; output SHALL NOT совпадать с input или находиться внутри assets, включая файловые aliases. Пустой inventory SHALL давать валидный semantic snapshot с нулём embeddings.

#### Scenario: Successful build and reopen
- **WHEN** build заканчивается и snapshot повторно открывается
- **THEN** каждому chunk соответствует его embedding, модельная identity сохранена, Markdown и provenance равны исходным

#### Scenario: Build failure or protected path
- **WHEN** inference/запись/validation/publication завершается ошибкой либо output указывает на input или assets
- **THEN** команда завершается ненулевым кодом без изменения input, assets и прежнего output

#### Scenario: Removed and empty inventory
- **WHEN** новый вход исключает прежние chunks либо содержит ноль chunks
- **THEN** опубликованный semantic snapshot содержит только новое inventory и точное соответствующее число embeddings

### Requirement: Read-only compatibility validation
Semantic reader SHALL открывать существующий файл без создания/модификации, проверять storage и semantic versions, identity модели/tokenizer/input format, полноту соответствия chunks/embeddings, dimension/dtype/длину binary data, finite values и нормы. Несовместимые, неполные, повреждённые и storage-only индексы SHALL отклоняться без fallback на произвольные vectors; mismatch SHALL требовать повторного построения совместимого semantic snapshot. Обычный storage-only CLI/reader SHALL сохранять текущий контракт и SHALL NOT требовать model assets. Отсутствие semantic snapshot SHALL NOT ломать существующий FastAPI startup/health.

#### Scenario: Incompatible model
- **WHEN** конфигурация query модели отличается от identity snapshot
- **THEN** retrieval не возвращает результаты и сообщает категорию несовместимости с необходимостью rebuild

#### Scenario: Invalid vectors or absent file
- **WHEN** файл отсутствует либо содержит missing/extra embedding, неверную dimension, NaN, zero vector или неподдерживаемую version
- **THEN** reader сообщает контролируемую ошибку и не создаёт/изменяет файл

#### Scenario: Storage remains independent
- **WHEN** storage-only import/reading или FastAPI health выполняются без embedding dependencies/assets
- **THEN** существующее поведение остаётся доступным без inference или сетевых обращений

#### Scenario: Base reader accepts additive semantic extension
- **WHEN** StorageReader открывает semantic snapshot с неизменной base v1 частью и additive semantic tables
- **THEN** он SHALL возвращать исходные documents/chunks без model dependencies/assets, сохраняя все проверки base schema/columns/PK/FK/unique keys, user_version, integrity, foreign_key_check, JSON и provenance; он SHALL NOT заявлять валидность embeddings

#### Scenario: Semantic extension cannot bypass base validation
- **WHEN** semantic snapshot содержит повреждённую base schema, данные или provenance
- **THEN** StorageReader и SemanticIndex SHALL отклонять snapshot по существующим base checks; SemanticIndex SHALL выполнять base validation до проверки extension

### Requirement: Ranked semantic chunk search
Система SHALL возвращать top-k chunks по cosine similarity нормализованных embeddings, с default k=10 и явно заданным положительным целым k. При k больше inventory SHALL возвращаться все chunks, при пустом inventory — пустой список. Результаты SHALL сортироваться по убыванию score и при равенстве по chunk ID по возрастанию. Каждый результат SHALL содержать rank, finite score, chunk ID и исходные metadata/provenance для lookup и дословного цитирования; source namespaces SHALL NOT смешиваться. Scores SHALL NOT считаться вероятностью ответа либо основанием автоматического отказа. Этот этап SHALL NOT добавлять lexical search, RRF, reranking или генерацию ответов.

#### Scenario: Known nearest vectors and ties
- **WHEN** query сравнивается с заранее известными нормализованными vectors, включая одинаковые scores
- **THEN** top-k и scores соответствуют cosine similarity, порядок ties стабилен, rank начинается с 1

#### Scenario: Source evidence preserved
- **WHEN** найден chunk с code/table continuation
- **THEN** результат сохраняет source identity, URL, headings, ranges и continuation metadata; generated segments не представлены дословной цитатой

#### Scenario: Ordinary retrieval uses only the supplied question
- **WHEN** вызывается `search(question, k)` или query CLI
- **THEN** retrieval SHALL использовать только переданный вопрос без хранения истории, context resolution или query rewriting

### Requirement: Administrative commands and measured baseline
Система SHALL предоставлять документированные offline команды build и query из app/ и Compose эквиваленты через существующий data mount. Build report SHALL включать counts и model/index identity без полного Markdown; diagnostics SHALL NOT включать credentials, вопрос или полный текст источников. Query JSON SHALL включать ranked results и provenance как явный результат поиска. Baseline SHALL использовать frozen evaluation corpus без изменения questions/reference/splits, показывать top-5 evidence hits и misses, live/synthetic и tuning/holdout отдельно, фиксировать corpus/index/model fingerprints, параметры, время и peak memory на указанной среде. Полный hit SHALL требовать покрытия всех обязательных source evidence ranges совокупностью source ranges top 5, а не совпадения страницы или generated text. Answerless/refuse/clarify SHALL показываться отдельно от denominator. Baseline SHALL NOT заявлять достигнутый MVP Hit@5 ≥90% без измерений и SHALL NOT делать этот порог условием готовности чистого semantic этапа.

#### Scenario: Reproducible baseline
- **WHEN** frozen live и synthetic snapshots проходят один и тот же semantic retrieval protocol
- **THEN** отчёт сохраняет fingerprints, отдельные split counts/hits/misses и case IDs, а corpus/reference bytes не меняются

#### Scenario: Partial composite evidence
- **WHEN** top 5 покрывает только одно из нескольких обязательных evidence либо только generated header
- **THEN** case считается miss независимо от page hit

#### Scenario: Evaluation-only follow-up protocol
- **WHEN** evaluate обрабатывает follow-up case frozen corpus
- **THEN** только evaluation adapter SHALL составлять `previous_question + "\n" + current_question` без ответов и передавать его обычному search с тем же query budget; overflow SHALL давать ошибку без shortening; отчёт SHALL указывать evaluation protocol v1 и отдельные follow-up counts/hits/misses/Hit@5 внутри live/synthetic × tuning/holdout, исключая эти cases из метрик обычного single-question retrieval
