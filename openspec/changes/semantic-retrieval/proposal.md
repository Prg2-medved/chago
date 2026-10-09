# Proposal

## Why

Ingestion, chunking и SQLite storage уже сохраняют документы и точную provenance, но пока не умеют находить chunks по смыслу вопроса. Этап 7 ROADMAP добавляет локальный semantic baseline для русского текста, на котором затем можно проверить пользу lexical/hybrid retrieval.

## What Changes

- Добавить CPU inference предварительно установленной `intfloat/multilingual-e5-small`: минимальный manifest assets по design, обязательная safetensors-only загрузка без pickle fallback, нормализованные 384-мерные embeddings, `query:`/`passage:`, проверка полного input без truncation и без runtime downloads.
- Построить из storage-only snapshot отдельный полный semantic SQLite snapshot с embeddings, модельной identity и сохранёнными документами/chunks; ошибки не заменяют прежний output.
- Предоставить Python API и административные CLI для построения индекса и top-k semantic search с scores и исходной metadata/provenance.
- Проверять совместимость модели, tokenizer и индекса; не использовать неполные или несовместимые embeddings. Базовый StorageReader читает base v1 часть semantic extension без ослабления существующей validation и без model dependencies/assets.
- Добавить воспроизводимый semantic baseline на frozen evaluation corpus с разделением live/synthetic и tuning/holdout, без заявления о готовности hybrid MVP. Композиция follow-up контекста ограничена evaluation protocol; её метрики отделены от обычного single-question retrieval, API/query CLI не получают обработку истории.
- Сохранить storage-only импорт и обычный FastAPI startup независимыми от модели. Lexical search, RRF, reranker, chat API/UI и orchestration полного reindex остаются вне scope.

## Capabilities

### New Capabilities

- `semantic-retrieval`: offline embedding-index build, совместимость semantic snapshot и поиск chunks по cosine similarity с проверяемой provenance.

### Modified Capabilities

Нет. Контракты storage-only CLI/reader, chunking и evaluation corpus сохраняются; semantic snapshot получает отдельный версионированный контракт поверх storage v1.

## Impact

Новые `app/app/embeddings.py`, `app/app/retrieval.py` и целевые tests; ограниченные дополнения storage для повторного использования проверенного snapshot writer/reader без ослабления validation. Конфигурация локальной модели и CPU limits в `app/app/config.py`, `.env.example`, Compose; CPU runtime dependencies в requirements/Dockerfile только при необходимости, с закреплением совместимых версий. Инструкции установки и baseline evidence — в новом `docs/semantic-retrieval.md`; README и ROADMAP не изменяются. Отдельный vector DB, внешний embedding API и новые services не требуются.
