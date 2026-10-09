# Design

## Context

Мотивация и scope — proposal.md. `app/app/index_storage.py` уже содержит StorageSnapshot/StoredChunk, validation JSON, read-only StorageReader и публикацию временного SQLite через replace. Storage v1 хранит documents/chunks/snapshot_metadata, проверяет schema, integrity и provenance; embeddings отсутствуют. `chunk_tokenizer.py` закрепляет E5 revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, tokenizers 0.22.2 и hashes трёх файлов; `passage()` задаёт точный input. Chunking считает special tokens без truncation. Requirements сейчас не содержат inference runtime или NumPy. FastAPI startup не загружает assets.

Frozen corpus и validator уже существуют; `evaluation.py` проверяет integrity, но не измеряет retrieval. Evidence размечено source ranges, не chunk IDs. Документ раннего CPU benchmark содержит измерения LLM и незавершённые проверки; это не evidence работоспособности embedding runtime.

## Goals / Non-Goals

**Goals:** повторно использовать проверенный snapshot и точный passage format; держать model/matrix lifecycle внутри явного retrieval объекта; получить standalone semantic baseline с измеряемыми ресурсами.

**Non-Goals:** подключение модели при HTTP startup, endpoint чата, hot reload, orchestration остановки app/Wiki.js, изменение frozen corpus, поддержка нескольких providers или автоматические schema migrations.

## Decisions

### 1. Один локальный CPU backend

Добавить `embeddings.py` с небольшим типизированным interface: identity, encode passages, encode query. Реализация — Sentence Transformers/PyTorch CPU и NumPy float32; lazy imports сохраняют storage/health независимыми от heavy libraries. Установка зависимостей — отдельный build/install шаг, закрепить совместимые версии с существующим tokenizers 0.22.2 и CPU-only torch wheels; если resolution конфликтует, выбрать совместимые версии backend, не менять tokenizer contract автоматически.

Загрузка только из проверенного существующего каталога, `local_files_only=True`, `device='cpu'`, `trust_remote_code=False`, offline environment до library initialization. Явный bounded batch size и threads (начальные значения 16 и 4). Отключить автоматические prompts, чтобы префиксы добавлялись ровно один раз. Проверять полный input через LocalE5 до encode и сверять tokenizer backend на одинаковые token IDs/special-token поведение; encode не получает inputs сверх лимита. Нормализовать и валидировать итоговые float32 vectors (норма с tolerance 1e-5).

Для MVP identity ограничена существующей model/revision; конфигурация задаёт expected identity и путь, mismatch отвергается. Interface позволяет позже заменить локальную модель без переписывания ranking; другие revisions/model IDs требуют согласованного обновления tokenizer contract и rebuild, этот этап их не обещает.

Альтернативы: raw Transformers потребовал бы самостоятельно обслуживать pooling; ONNX добавил бы export/runtime и отдельную identity; внешнее API нарушает offline requirement. API загрузки локального каталога и offline flags подтверждены [официальной документацией SentenceTransformer](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).

### 2. Предварительная установка с manifest

В отдельном installation step подготовить минимальный набор assets выбранной revision: `model.safetensors`, `config.json`, `modules.json`, `sentence_bert_config.json`, `1_Pooling/config.json`, `tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`. Использовать fast tokenizer из `tokenizer.json`; `sentencepiece.bpe.model`, `pytorch_model.bin`, ONNX/OpenVINO и остальные файлы snapshot не обязательны. Hashes обязательных файлов закрепить в проверяемом manifest проекта после проверки [официального snapshot](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3). Manifest не генерируется runtime из произвольных assets. Loader явно передаёт `use_safetensors=True` через model kwargs; отсутствие/повреждение safetensors или невозможность такой загрузки завершают операцию ошибкой, без fallback на pickle/`pytorch_model.bin`, даже если он присутствует. Запрет remote code сохраняется. Сверить tokenizer hashes с ASSET_HASHES; corpus tokenizer identity должна совпадать с фактической LocalE5 identity. Local path в data mount; output запрещён внутри assets. Новые env настройки отделить от HTTP settings и валидировать при явном build/query.

### 3. Additive semantic extension поверх storage v1

Сохранить `PRAGMA user_version=1` и исходные таблицы неизменными; semantic format v1 обозначать отдельной singleton `embedding_metadata` и таблицей `chunk_embeddings(chunk_id PRIMARY KEY REFERENCES chunks, vector BLOB NOT NULL)`. Metadata: format_version, model ID/revision, manifest fingerprint, tokenizer fingerprint, dimension=384, dtype='<f4', normalized=true, input_format_version=1, backend/package versions для воспроизводимости. Для каждого chunk vector — ровно 1536 bytes little-endian float32, без pickle.

StorageReader читает как storage-only v1, так и base часть semantic snapshot с additive tables, без model assets/dependencies, и не заявляет валидность embeddings. Все существующие проверки base schema, columns, PK/FK/unique keys, user_version, integrity, foreign_key_check, JSON и provenance сохраняются; semantic extension не позволяет пропускать их или принимать повреждённую base часть. SemanticIndex сначала использует эту base validation, затем отдельно проверяет extension schema, PK/FK/uniqueness, metadata, взаимно однозначное покрытие IDs и vector values/norms. Хранить per-vector mapping по ID, не доверять случайному row order. Storage-only output по-прежнему имеет только base tables. Поэтому существующий sqlite-index-storage контракт не меняется; semantic feature имеет свой spec.

Альтернативы: storage v2 потребовал бы изменения существующего reader/version contract и миграций; sidecar vectors создаёт проблему согласованности; vector DB избыточна для текущего корпуса.

### 4. Полный standalone build

`python -m app.embeddings build --input <storage.db> --output <semantic.db> --model-path <dir>` читает source read-only, валидирует snapshot и assets, пересчитывает полный passage budget, строит все vectors batches и пишет новое inventory. Выделить минимальный внутренний helper записи base snapshot из index_storage, сохранив прежний public CLI и checks; semantic writer добавляет свои tables до публикации. После закрытия writer повторно открыть base и semantic readers, проверить данные/relations/vector coverage, затем replace временного файла в output directory. При ошибке временный файл очищается, input и прежний output сохраняются. Никаких in-place upgrades. Даже пустой индекс проверяет model identity/assets, inference на пустом batch не вызывается.

Атомарная публикация standalone snapshot продолжает storage pattern; полный ingestion→chunking→reindex с остановкой app остаётся отдельным change. Readers закрываются до replace на Windows.

### 5. Простое точное ranking

`retrieval.py` загружает один semantic snapshot и immutable NumPy matrix в порядке chunk IDs, вместе с соответствующими StoredChunk. Проверяет identity относительно encoder до query. Один retrieval объект удерживает encoder и matrix для повторных вопросов; CLI создаёт объект один раз на invocation. `search(question, k=10)` валидирует input/k, кодирует query, вычисляет matrix dot query (cosine для нормализованных vectors), сортирует по score descending/chunk ID ascending; full sort достаточен для сотен/тысяч chunks. Не вводить threshold, dedup, соседние chunks или score calibration.

`python -m app.retrieval query --index <semantic.db> --model-path <dir> --question <text> --top-k 10` выводит JSON результатов с rank/score/chunk и source metadata, source/generated segments, ranges, structure. Не печатать вопрос/source text в errors/logs. Командные аргументы подходят для административного baseline; будущий HTTP UX сюда не входит.

### 6. Baseline как отдельная retrieval оценка

Добавить `python -m app.retrieval evaluate` с путями manifest/questions, frozen live reference, live semantic index, и отдельным synthetic index/reference. Переиспользовать corpus validation, не ослабляя его и не изменяя integrity CLI. Проверить соответствие каждого index frozen inventory/content hashes и input settings; неверный corpus/index отклоняется. Только evaluation adapter составляет follow-up input как `previous_question + "\n" + current_question` без предыдущих ответов и передаёт его обычному `search`; query-budget overflow — явная ошибка, без тихого shortening. Зафиксировать эту композицию как evaluation protocol v1 и покрыть тестом. `search(question, k)` и query CLI используют только переданный вопрос, не хранят историю и не выполняют context resolution/query rewriting. Follow-up cases с составленным input, их counts/hits/misses/Hit@5 показывать отдельной группой в каждой live/synthetic × tuning/holdout секции, не включать в метрики обычных single-question cases; указывать protocol version. Это evaluation convention, не продуктовый chat contract.

Case hit: объединить source ranges top 5 по source/page_id, проверить полное покрытие каждого обязательного evidence range, включая составные и конфликтующие источники. Source/generated distinction обязателен. В denominator — только соответствующие answerable cases с evidence по corpus protocol; partial_answer/report_conflict с требуемой evidence включаются, refuse/clarify отдельно. Показать counts, rates, case IDs/misses раздельно live/synthetic × tuning/holdout. Не подбирать параметры на holdout и не печатать полные live документы. Зафиксировать fingerprints, embedding/runtime identity, settings, latency и memory; corpus bytes проверить до/после.

Порог ≥90% относится к итоговому MVP protocol; низкий semantic baseline записывается как результат для hybrid этапа, а не скрывается подбором corpus. Unit geometry tests не доказывают качество русского поиска; реальный offline run обязателен для соответствующей приёмки.

## Risks / Trade-offs

- [CPU torch размер и совместимость] → CPU-only install, pinned compatible versions, targeted dependency/import smoke и memory benchmark; не добавлять accelerator packages.
- [Library truncation/prompts] → preflight полного input, token IDs parity, отключённые defaults, тест 512/513 и реальный offline inference.
- [Ошибочная manifest identity] → закреплённая revision и review hashes во время установки; runtime не доверяет self-declared manifest assets.
- [Все vectors в RAM] → подходит текущему корпусу; фиксировать peak memory и retrieval timings, пересмотреть только при росте корпуса.
- [Scores без надёжной answerability] → возвращать ranking без automatic refusal; unanswerable cases измерять отдельно.
- [Нет assets/целевого сервера] → deterministic unit tests отдельно от реальной приёмки; не отмечать измерения выполненными или apply tasks закрытыми без evidence.

## Migration Plan

Сначала установить pinned CPU dependencies и модель с проверенными assets, сохранив существующий storage.db. Построить semantic snapshot в отдельный output, проверить reopen/query/offline baseline; команды Compose использовать через существующий `/data`, без нового сервиса. Предыдущие storage snapshots остаются читаемыми; semantic query отвергает их без embeddings. Rollback — удалить использование нового semantic output и вернуть предыдущий совместимый semantic snapshot/config; storage-only pipeline не мигрирует. HTTP integration последует отдельным этапом.
