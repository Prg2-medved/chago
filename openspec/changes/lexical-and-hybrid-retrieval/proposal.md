# Proposal

## Why

Чистый semantic retrieval уже работает, но measured baseline на frozen corpus показывает live single-question Hit@5 5/9 для tuning и 0/3 для holdout. Этап 8 ROADMAP и §12 SPEC предусматривают lexical branch для технических identifiers и объединение результатов, качество которого можно воспроизводимо сравнить с этим baseline.

## What Changes

- Добавить SQLite FTS5/BM25 по title, heading path и search_text chunks со стандартным `unicode61` и безопасным преобразованием пользовательского вопроса в поисковые термы.
- Поднимать lexical-кандидатов с буквальными совпадениями явно заданных IP, путей, имён с дефисом и текста в обратных кавычках; различать похожие identifiers и сохранять связь совпадений с исходным Markdown.
- Строить отдельный полный snapshot, дополняя существующий semantic SQLite файл lexical index без повторного embedding inference и без изменения входа, IDs, vectors или provenance.
- Добавить hybrid API/CLI: semantic top 10 + lexical top 10, RRF с константой 60, default final top 6 уникальных chunks; параметры сделать конфигурируемыми.
- Сохранить существующий semantic API/CLI и добавить сравнение semantic, lexical и hybrid на неизменном `rag-evaluation-corpus` с протоколом evidence Hit@5, разделением namespaces, splits и follow-up.
- Выполнить измерения и явно показать достижение или недостижение целевого live Hit@5 ≥90%; не добавлять reranker, генерацию ответов или orchestration полного reindex.

## Capabilities

### New Capabilities

- `lexical-retrieval`: versioned FTS5 extension, offline build, read-only keyword search, exact technical literals и административные команды.
- `hybrid-retrieval`: согласованные semantic/lexical branches одного snapshot, детерминированный RRF, конфигурация, provenance и измеренное сравнение трёх режимов.

### Modified Capabilities

- `semantic-retrieval`: уточнить границу Ranked semantic chunk search — pure semantic mode сохраняет прежний контракт, а отдельный hybrid mode может использовать его результаты для lexical/RRF composition.

## Impact

Планируемые новые модули: `app/app/lexical_storage.py`, `app/app/lexical_retrieval.py`, `app/app/hybrid_retrieval.py`. Точечные изменения затронут `index_storage.py`/`semantic_storage.py` для общего validated handle, `retrieval.py` для переиспользования прежнего cosine ranking, `config.py` и административные environment примеры для retrieval settings, `retrieval_evaluation.py` для общего протокола сравнения. Потребуются связанные tests и `docs/lexical-and-hybrid-retrieval.md` с measured report; `README.md`, `ROADMAP.md`, frozen corpus и прежний baseline не изменяются.

Используется стандартный `sqlite3`; новые Python dependencies и внешние сервисы не планируются. Base storage v1 и semantic format v1 остаются совместимыми; прежние индексы пригодны для semantic query, а новый lexical/hybrid режим требует отдельно построенного FTS5 extension. HTTP startup/health остаются независимыми от retrieval, модель работает локально на CPU.
