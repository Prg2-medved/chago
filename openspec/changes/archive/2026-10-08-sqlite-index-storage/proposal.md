# Proposal

## Why

Ingestion и chunking уже создают проверенные локальные JSON snapshots, но постоянного хранилища для чтения будущими retrieval-компонентами нет. Этап 6 ROADMAP требует воспроизводимого сохранения документов, chunks и служебных метаданных в одном SQLite-файле.

## What Changes

- Добавить offline импорт существующего chunking output schema_version 1 в SQLite и типизированный read API.
- Сохранять исходный Markdown, source identity, metadata документов, все поля chunks и точную provenance цитат.
- Версионировать storage schema, сохранять algorithm/settings/tokenizer identity и проверять целостность перед публикацией файла.
- Предоставить административную CLI с явными input/output путями и безопасными ошибками; повторный импорт создаёт полный snapshot без накопления старых записей.
- Embedding inference и хранение векторов, FTS5/search, app startup loading и orchestration полного reindex остаются последующим изменениям ROADMAP. Это промежуточный storage snapshot, ещё не готовый retrieval index из SPEC.md.

## Capabilities

### New Capabilities

- `sqlite-index-storage`: локальное сохранение и чтение проверенного chunking snapshot без потери данных и с контролем совместимости.

### Modified Capabilities

Нет. Существующие ingestion/chunking CLI и JSON contracts сохраняются.

## Impact

Новые `app/app/index_storage.py`, целевые storage/CLI tests и `docs/sqlite-index-storage.md`. Используется стандартный Python sqlite3 без новых зависимостей; текущий Compose mount ./data:/data достаточен. README.md, ROADMAP.md, FastAPI startup, Wiki.js и frozen evaluation corpus не изменяются.
