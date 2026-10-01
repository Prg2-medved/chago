# Proposal

## Why

Для следующих этапов chunking и indexing нужен воспроизводимый набор исходного Markdown Wiki.js. Проверенный доступ через прежний транспорт не позволяет читать содержимое страниц с минимальными правами, поэтому источником становится административно подготовленный PostgreSQL view с технически read-only доступом.

## What Changes

- Читать полный результат стабильного versioned view отдельной ingestion-ролью: только CONNECT, USAGE и SELECT view, без доступа к внутренним таблицам и write/DDL permissions.
- Делегировать view отбор допустимых опубликованных Markdown-страниц с учётом периода публикации и общей аудитории RAG; неизвестные, неоднозначные и неподтверждённые состояния исключать по fail-closed контракту; mapping отдельно подтверждать административной live-проверкой.
- Проверять обязательные поля, типы и уникальность строк; сохранять lossless Markdown, метаданные, source URL и SHA-256 в frozen document model.
- Получать полный локальный детерминированный JSON snapshot ручной CLI-командой, заменяя старый файл только после полного успеха.
- Добавить изолированную конфигурацию environment/secrets, offline fixtures/mock DB tests и инструкцию административной подготовки и эксплуатации.

## Capabilities

### New Capabilities

- `wikijs-markdown-ingestion`: read-only получение Markdown-документов через PostgreSQL view в полный локальный воспроизводимый снимок.

### Modified Capabilities

Нет. Запуск приложения, `/health` и локальная LLM сохраняют свой контракт.

## Impact

Планируются `app/app/wiki_client.py`, `app/app/ingestion.py`, отдельный loader в `app/app/config.py`, тесты/fixtures в `app/tests/`, настройки `.env.example` и `compose.yaml`, инструкция `docs/wikijs-markdown-ingestion.md`. Допускается один PostgreSQL driver (psycopg 3); DB abstraction/provider framework не нужен. Снимки хранятся в игнорируемом `data/`. View и роль готовит администратор отдельно от приложения после live-проверки схемы. SPEC.md согласуется с новой границей интеграции; README.md и ROADMAP.md не меняются.

## Non-goals

Chunking, SQLite/indexing, embeddings, retrieval, Web UI, генерация ответов, расписание, incremental ingestion, синхронизация per-user ACL, assets/вложения, произвольный SQL, SQL tools у LLM, прямой доступ LLM к PostgreSQL и любые изменения объектов Wiki.js из runtime не входят в этот этап.
