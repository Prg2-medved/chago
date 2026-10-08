# sqlite-index-storage Specification

## Purpose

Сохранять результат offline Markdown chunking в локальном SQLite snapshot и предоставлять воспроизводимое чтение документов, chunks и provenance для будущих retrieval-компонентов.

## Requirements

### Requirement: Validated offline import
Система SHALL принимать существующий chunking JSON schema_version 1 без Wiki.js, LLM, tokenizer assets и сетевых обращений. До публикации SHALL проверяться типы и версии, source identity, hashes документов, уникальность document identities и chunk IDs, ссылки chunks на документы, совпадение дублированных metadata, допустимость ordinal и token counts, segments и source ranges. Диапазоны SHALL измеряться в Unicode code points; search_text SHALL соответствовать последовательности source/generated segments. Неизвестная версия или некорректный вход SHALL отклоняться целиком.

#### Scenario: Valid offline import
- **WHEN** импортируется корректный chunking output при отсутствии tokenizer assets и Wiki.js credentials
- **THEN** создаётся читаемый SQLite snapshot с теми же документами, chunks и служебными метаданными без сетевых обращений

#### Scenario: Invalid provenance
- **WHEN** chunk ссылается на отсутствующий документ, содержит неверные metadata, дубликат ID или диапазон вне Markdown
- **THEN** импорт завершается ошибкой и прежний output остаётся неизменным

### Requirement: Lossless storage and source isolation
Хранилище SHALL сохранять дословный Markdown, все document metadata, chunk IDs, heading paths, ordinal, search_text, token counts, structure, упорядоченные source/generated segments и source_ranges. Document identity SHALL включать source origin и page_id; namespaces SHALL NOT сливаться. Пустой snapshot и документы без chunks SHALL сохраняться корректно.

#### Scenario: Exact source round trip
- **WHEN** сохраняются русский текст, CRLF, code/table continuation и generated segments
- **THEN** после чтения Markdown и скалярные поля равны входным, вложенные структуры семантически эквивалентны с сохранением порядка массивов, source slices дают точные исходные цитаты и generated segments остаются отличимыми от них

#### Scenario: Source namespaces
- **WHEN** два отдельных snapshots имеют один page_id и разные source origins
- **THEN** прочитанные document identities сохраняют разные origins и не считаются одной страницей

#### Scenario: Empty content
- **WHEN** вход содержит ноль документов либо документ с пустым Markdown и нулём chunks
- **THEN** читается соответствующий inventory без искусственных chunks

### Requirement: Versioned deterministic reading
Хранилище SHALL сохранять storage schema version, input schema/algorithm version, source, tokenizer identity/fingerprint и chunking settings. Read API SHALL возвращать документы в порядке source/page_id, chunks в порядке source/page_id/ordinal/chunk_id и предоставлять lookup по chunk ID с явным отсутствием неизвестного ID. Повторное сохранение одинакового входа SHALL давать одинаковые логические данные; побайтовое равенство SQLite-файлов не требуется. Reader SHALL открывать файл без изменения и без автоматического создания отсутствующей БД, отвергать повреждённую или неподдерживаемую schema. Tokenizer identity SHALL NOT представляться как доказательство наличия embeddings.

#### Scenario: Repeated persistence
- **WHEN** одинаковый snapshot сохраняется повторно и читается после закрытия и повторного открытия файла
- **THEN** metadata, inventory, IDs, порядок и содержимое совпадают без дублирования записей

#### Scenario: Missing or incompatible database
- **WHEN** запрошенный файл отсутствует, повреждён или имеет неподдерживаемую storage version
- **THEN** reader сообщает контролируемую ошибку без создания либо изменения файла

### Requirement: Complete snapshot publication
Система SHALL публиковать SQLite файл только после полного успешного импорта, закрытия записи и проверки целостности/связей. Ошибка validation, записи или публикации SHALL сохранять прежний output и исходный JSON, возвращать ненулевой exit code и безопасную категорию без исходного текста или credentials. Новый snapshot SHALL полностью заменять inventory прежнего, включая удаление отсутствующих документов и chunks. CLI SHALL отклонять output, совпадающий с input, включая файловые aliases.

#### Scenario: Failure preserves previous snapshot
- **WHEN** запись, integrity check либо замена файла завершается ошибкой
- **THEN** прежний SQLite snapshot и input остаются неизменными, частичный snapshot не публикуется

#### Scenario: Removed page
- **WHEN** новый полный snapshot не содержит страницу из прежнего файла
- **THEN** успешный импорт оставляет только новый inventory без chunks удалённой страницы

#### Scenario: Protected input
- **WHEN** output указывает на input напрямую либо через symlink/hardlink
- **THEN** CLI отклоняет запрос до изменения input

### Requirement: Administrative CLI and isolation
Система SHALL предоставлять `python -m app.index_storage --input <chunks.json> --output <snapshot.db>` из app/ и документированный Compose эквивалент через существующий data mount. Успешный отчёт SHALL включать document/chunk counts и storage version без содержимого документов. Обычный FastAPI startup SHALL оставаться независимым от наличия storage файла. Этот этап SHALL NOT выполнять embedding inference, retrieval, FTS search или orchestration остановки/запуска app.

#### Scenario: Successful administrative command
- **WHEN** CLI вызывается с корректным input и доступным output каталогом
- **THEN** команда возвращает код 0, сохраняет snapshot и сообщает counts/version

#### Scenario: Application without database
- **WHEN** app запускается без SQLite snapshot
- **THEN** существующие startup/health работают как прежде
