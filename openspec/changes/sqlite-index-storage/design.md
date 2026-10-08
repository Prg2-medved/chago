# Design

## Context

См. proposal.md — Why. `ingestion.Document` содержит page_id, locale, path, title, source_url, updated_at, markdown и content_sha256. `chunking.build_output` создаёт JSON version 1 с source, algorithm_version, tokenizer identity, settings, documents и chunks. Chunks включают дублированные document metadata, segments, source_ranges, search_text, structure и token counts. Готового parser этого output и SQLite storage пока нет. Compose уже монтирует ./data в /data; pytest и mypy присутствуют.

ROADMAP разделяет storage, semantic retrieval, lexical retrieval и atomic-full-reindex. SPEC.md описывает конечный файл с embeddings и FTS5; текущий этап создаёт только основу этого файла. Его нельзя считать завершённым индексом для ответов пользователям.

## Goals / Non-Goals

**Goals:** типизированное чтение без потери provenance, проверка входного contract и публикация целого storage snapshot; минимальная зависимость от существующего chunking кода.

**Non-Goals:** миграции неизвестных schemas, byte-identical SQLite, incremental updates, concurrent writers, app hot reload и orchestration reindex. Embeddings/BLOB model metadata и FTS5 добавляются будущими changes, когда появятся соответствующие consumers.

## Decisions

### Один storage module и стандартный sqlite3

Добавить `app/app/index_storage.py` с typed snapshot/chunk records, validation, writer, read-only reader и CLI. Переиспользовать `Document`; storage module не импортирует LocalE5 и не загружает tokenizer. ORM и отдельные сервисы не нужны для малого snapshot. Извлечение общего parser из chunking отклонено как лишний рефакторинг: новый parser проверяет уже готовый output, а не повторяет алгоритм разбиения.

### Нормализованные identities и JSON для вложенных полей

Storage schema v1:
- `snapshot_metadata`: singleton с source, input schema/algorithm version, tokenizer JSON и settings JSON; storage version дополнительно фиксируется в PRAGMA user_version.
- `documents`: составной PK (source, page_id), UNIQUE(source, locale, path), все поля Document, включая дословный Markdown.
- `chunks`: PK chunk_id, FK (source, page_id), UNIQUE(source, page_id, ordinal), search_text, token counts; heading_path, ordered segments, source_ranges и structure как canonical JSON TEXT.

Дублированные chunk document metadata восстанавливаются join с documents; импорт проверяет их равенство. Это исключает расхождение двух copies. Один файл содержит один полный source snapshot, как текущий output; source является частью document identity текущего chunking contract и поэтому сохраняется в ключе вместе с page_id. Monolithic JSON blob отклонён: будущим consumers нужны lookup и inventory без разбора всего файла. JSON вложенных структур сохраняет ordered provenance без преждевременной нормализации всех видов code/table metadata.

### Validation и typed reader

Parser строго проверяет bool/int distinction, версии, обязательные поля, документные hashes/identity/URL/timestamps, chunk ссылки и уникальность, ordinal и допустимые token counts, segment kinds/ranges/generated reasons, согласованность source_ranges и search_text. Tokenizer metadata и settings проверяются структурно и сохраняются; storage не пересчитывает E5 counts и не заявляет независимую проверку tokenizer assets. Неизвестные input versions отклоняются; algorithm identity сохраняется, а не интерпретируется как storage version.

Reader использует read-only SQLite URI, проверяет user_version, обязательную структуру, metadata и integrity/foreign keys, возвращает typed records с явным стабильным ORDER BY и lookup с None для отсутствующего chunk. Отсутствующий файл даёт контролируемую ошибку; readonly open не создаёт пустую БД. Полные проверки приемлемы для небольшого корпуса; lazy high-scale reading пока не требуется.

### Новый файл вместо изменения активной БД

CLI требует явные input/output: безопасный пример output `/data/storage-snapshot.db`, конечное имя `/data/rag.db` выберет будущий indexer. Validate input до записи; создать временную БД рядом с output, включить foreign_keys, записать всё в одной transaction, commit, закрыть, повторно открыть readonly и выполнить integrity_check/foreign_key_check и проверку counts. Закрыть reader перед os.replace, очистить временные файлы при ошибке. Использовать обычный rollback journal без WAL, чтобы публикация не зависела от sidecar файлов. Защита input включает resolve и samefile.

In-place DELETE/INSERT transaction отклонена: отдельный файл упрощает сохранение прежнего snapshot при любых ошибках. Эта локальная гарантия writer не реализует будущую pipeline ingestion → embeddings → app restart. Команда предназначена для offline административного применения без открытых consumers и параллельных writers.

## Risks / Trade-offs

- [SQLite replacement при открытом файле на Windows может завершиться ошибкой] → все собственные connections закрываются; чужой reader приводит к контролируемой ошибке с сохранением старого output.
- [Сложная provenance может быть потеряна при сериализации] → exact round-trip тесты Unicode/CRLF, generated segments, code/table continuation и source slices.
- [Memory usage полного JSON] → соответствует существующему snapshot pipeline и малому корпусу; streaming не добавляется.
- [Новые retrieval stages потребуют новой storage version] → reader отвергает неизвестную версию; производный файл пересоздаётся из snapshots вместо автоматической миграции.
- [Storage-only файл ошибочно воспринимается как рабочий RAG index] → отдельное примерное имя и документация стадии, отсутствие embeddings явно отражено; app пока не загружает этот файл.

## Migration Plan

Добавить module, targeted tests и `docs/sqlite-index-storage.md` с local/Compose командами и границами стадии. Прежние JSON сохраняются и остаются источником воспроизводимого импорта. Existing app deployment менять не требуется. Rollback — прекратить использование новой административной команды; старые JSON и app поведение сохраняются. При будущей смене schema потребуется пересоздание производного SQLite файла.
