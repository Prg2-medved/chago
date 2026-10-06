# Proposal

## Why

Ingestion уже сохраняет исходный Markdown и метаданные Wiki.js, но ещё не преобразует документы в воспроизводимые поисковые фрагменты. Этап 5 ROADMAP.md и §8 SPEC.md требуют структурного chunking с точными командами, контекстом разделов и проверяемой связью с источником до подключения поиска.

## What Changes

- Добавить детерминированный Markdown chunker для заголовков, текста, fenced code/Bash, таблиц и больших страниц.
- Сохранять source identity, title/path/locale/URL, heading path, порядковый номер, стабильный chunk ID и диапазоны исходного Markdown.
- Отделить дословные исходные фрагменты от добавленных heading/table/fence элементов поискового представления; помечать части длинных команд.
- Считать размер локальным токенизатором multilingual-e5-small: target 350, maximum 450, overlap около 50; полный passage input с metadata и special tokens не более 512 без truncation.
- Предоставить offline CLI snapshot → chunks JSON и проверки сохранности на существующем frozen evaluation corpus.
- Не добавлять embeddings, retrieval, SQLite, reindex orchestration, LLM/API/UI. README.md и ROADMAP.md не изменять.

## Capabilities

### New Capabilities

- `markdown-chunking`: структурное разбиение локальных Markdown-документов с E5 token budget, provenance и воспроизводимым offline output.

### Modified Capabilities

Нет. Контракты ingestion snapshot и frozen evaluation corpus сохраняются; chunking использует их как входные данные.

## Impact

Планируемые области: новый `app/app/chunking.py`, целевые tests/fixtures, `docs/markdown-chunking.md`; при необходимости отдельный небольшой tokenizer helper. Для реального подсчёта необходима минимальная закреплённая tokenizer-only зависимость и предварительно установленный локальный tokenizer E5 конкретной immutable revision `intfloat/multilingual-e5-small`; embedding runtime/weights не требуются. Output фиксирует model ID, immutable revision, fingerprint фактически используемых assets и версию pinned package `tokenizers`; будущий embedding stage использует совместимый tokenizer той же model revision. Runtime network fallback отсутствует. CLI settings изолированы от HTTP startup. Compose CLI читает assets из `data/tokenizers/` через существующий mount `./data:/data`, без отдельного постоянного tokenizer mount и без изменений обычного app startup/health; assets обязательны только для CLI. `.env.example` при необходимости описывает локальный tokenizer path. Существующие snapshot/reference/questions не перезаписываются.
