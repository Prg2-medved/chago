# Design

## Context

Мотивация — в [proposal.md](proposal.md). Контракты — в delta specs `lexical-retrieval`, `hybrid-retrieval`, `semantic-retrieval`.

Наблюдаемая реализация:

- `index_storage.py`: base storage v1, typed `StoredChunk`/`StorageSnapshot`, validation source ranges и read-only `StorageReader`. Проверка схемы допускает additive tables без ослабления проверки base tables.
- `semantic_storage.py`: additive semantic format v1, 384-dimensional normalized vectors; `SemanticReader` проверяет extension через handle base reader, затем закрывает его. Writer публикует отдельный temporary file после reopen checks.
- `retrieval.py`: `SemanticIndex.search(question, k=10)`, точный cosine и tie по chunk ID, `SearchResult(rank, score, chunk)`, query/evaluate CLI. JSON не включает полный document Markdown.
- `retrieval_evaluation.py`: protocol v1, evidence coverage по source ranges, separate follow-up, namespaces/splits. Сейчас тип и report builder связаны с `SemanticIndex` и `index.encoder.settings`.
- Frozen reference: 24 live pages, 910 semantic chunks; synthetic snapshot — 1 document/1 chunk. `docs/semantic-retrieval.md` и существующий baseline показывают live single-question 5/9 tuning, 0/3 holdout; follow-up 0/1 в каждом split. Holdout уже был измерен, поэтому новая проверка не является blind evaluation.
- SQLite предоставляется Python runtime; Docker использует `python:3.12-slim`. Наличие FTS5 на каждой целевой сборке ещё должно проверяться. Embedding dependencies и assets уже предусмотрены, HTTP startup их не загружает.

`SPEC.md` §§11–12 задаёт FTS5/BM25, стандартный unicode61, literal priority, RRF 10/10/60 и примерно top 6. Исторически этап 4 и задача 5.5 требовали измеряемый Hit@5 ≥90% до завершения этого change; результат 6/12 не выполнил этот критерий. Решение владельца от 2026-10-09 отделяет техническое завершение от качества: обязательный порог MVP сохранён в §§12.5, 27 и проверяется на отдельном этапе 4а. Запрет lexical/RRF в существующей semantic spec относится к pure semantic этапу: delta уточняет эту границу, сохраняя его API. Storage/evaluation corpus specs не меняются.

## Goals / Non-Goals

**Goals:** один self-contained snapshot для cosine и FTS, branch-level diagnostics, reproducible ranking, отдельный lexical режим без тяжёлых embedding imports, evidence comparison с прежним протоколом.

**Non-Goals:** изменение frozen questions/splits/reference/chunking, Russian stemming/synonyms, model replacement, reranker, answer generation, HTTP search endpoint/UI, runtime conversation resolution, ACL, orchestration atomic full reindex из следующего этапа ROADMAP. Local snapshot publication повторяет уже существующий storage pattern.

## Decisions

### 1. Additive FTS extension одного semantic snapshot

Новый `app/app/lexical_storage.py` строит extension из существующего **semantic** snapshot. Build не выполняет inference и не требует model assets: semantic validation использует сохранённые identity/vectors и существующие локальные dependencies. Storage-only build не добавляется: он не нужен для следующего шага текущего pipeline. Lexical query читает полученный файл без импорта NumPy/torch/embedding backend.

Предлагаемая schema:

```sql
CREATE TABLE lexical_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    metadata TEXT NOT NULL
);
CREATE VIRTUAL TABLE chunk_fts USING fts5(
    chunk_id UNINDEXED, title, heading_path, search_text,
    tokenize='unicode61'
);
```

Использовать обычную content-bearing FTS table с `detail=full`, без external-content triggers. Title и heading path (`" > ".join(...)`) берутся из validated chunks, body равен search_text; никаких E5 prefixes. Все три searchable columns имеют одинаковый BM25 weight 1.0. Insert order/rowids определяются ascending chunk ID; reader отдельно проверяет уникальность `chunk_id`, поскольку FTS table её не обеспечивает. Rowids остаются внутренней деталью.

Metadata format v1 содержит input format v1, tokenizer/options, query policy v1, literal policy v1, document/chunk counts, SQLite version и compile options. Runtime требует поддерживаемую schema/policy и фактический FTS5 capability, но не побайтовое совпадение compile options с build host. SQLite identity фиксируется для воспроизводимости; policy mismatch требует rebuild.

Build открывает input read-only, делает `sqlite3.Connection.backup()` в отдельный temporary file в output directory и валидирует скопированную base/semantic часть до дополнения. Предыдущий lexical extension при rebuild удаляется только в temporary copy; заново создаются все FTS rows и metadata. После записи закрываются handles, выполняются base/semantic/lexical reopen checks, сравниваются inventory, metadata и raw embedding bytes с исходной копией. Только затем `os.replace` публикует output. Failures удаляют только собственные temporary artifacts. Input/output aliases и пути/aliases assets отклоняются по существующему protection pattern; путь assets нужен только для path protection, каталог не обязан существовать. Base `user_version=1` и semantic format v1 сохраняются.

Альтернатива — второй DB-файл для FTS. Отклонена: потребовала бы контроля совпадения двух поколений и усложнила бы provenance, rollback и будущий full reindex. Content duplication в FTS принимается для текущих сотен/тысяч chunks; external-content экономия сейчас не оправдывает synchronization triggers.

### 2. Полная validation с сохранением read-only источника

`LexicalReader` проверяет base schema/data/provenance, lexical metadata/schema/options, exact content и полный набор IDs. Проверять только counts недостаточно: stale text либо повреждённые postings могут менять ranking без изменения inventory.

На disposable in-memory backup того же открытого read-only DB handle выполняется `INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')`. Для выбранной обычной content-bearing table встроенная проверка обнаруживает повреждение index structures и несоответствие postings собственному content ([SQLite FTS5 integrity-check](https://www.sqlite.org/fts5.html#the_integrity_check_command)). Отдельное точное сравнение всех FTS rows с validated chunk IDs/title/headings/search_text остаётся обязательным: внутренне согласованный индекс с устаревшим content проходит integrity-check, но не эту сверку. Reference FTS и comparison vocabulary для validation не нужны; `fts5vocab` остаётся только в query tokenizer probe из решения 3. Эти служебные writes никогда не выполняются в query file; успешная проверка не выполняет repair/rebuild. In-memory copy освобождается после validation; resource cost учитывается в benchmark.

Для `HybridIndex` надо точечно выделить semantic extension loading/validation из `SemanticReader` в helper, принимающий уже открытый validated base reader/connection. В обоих ветках используются один handle и одна read transaction; transaction начинается до base checks. При необходимости добавить private shared-reader entry point в `index_storage.py`, сохраняя публичный constructor/context manager. Semantic matrix, chunks и lexical SQL относятся к одному поколению. Pure `SemanticReader` продолжает владеть и закрывать своим base reader. Hybrid/Lexical indexes явно закрывают retained connection через context manager, включая failures.

Решение о едином handle исключает ситуацию, когда `SemanticIndex(path)` прочитал старый файл, а следующий `LexicalIndex(path)` открыл новый. Открывать путь дважды и сравнивать только IDs недостаточно при одинаковых IDs и изменившихся данных. Новая query не обещает live refresh: reload/new instance нужен для нового snapshot. На Windows публикация поверх открытого handle может быть отклонена ОС; build сохраняет прежний output, отдельная orchestration не добавляется.

### 3. Безопасная query policy v1

`app/app/lexical_retrieval.py` содержит typed `LexicalIndex`, `LexicalResult` и query CLI. Непустой Unicode string проверяется независимо от k; malformed text получает безопасную категорию. Lexical-only не получает E5 token budget, semantic/hybrid сохраняют прежний предел 512.

Чтобы использовать тот же tokenizer без приблизительной Python regex для Unicode, query terms извлекаются через reusable отдельный in-memory FTS5 probe и `fts5vocab`. После каждого вопроса probe content заменяется и не хранит историю. Уникальные terms сортируются детерминированно, заключаются в двойные кавычки с удвоением внутренних кавычек и объединяются OR. Только сформированное expression передаётся как bound SQL parameter. Если terms отсутствуют, MATCH не вызывается; literal scan всё равно возможен. Stopwords, morphology и synonym expansion не добавляются.

По [официальной документации SQLite](https://www.sqlite.org/fts5.html#unicode61_tokenizer), стандартный unicode61 разделяет пунктуацию и выполняет case folding. [FTS5 BM25](https://www.sqlite.org/fts5.html#the_bm25_function) выдаёт лучшие совпадения с меньшим score, поэтому keyword order — ascending BM25. Операторы пользовательского текста не сохраняются как FTS syntax.

Альтернативы: raw MATCH нарушает контракт обычного вопроса; quoted whole question превращает его в слишком строгую phrase; ручная tokenization может расходиться с runtime unicode61. OR terms с authoritative tokenizer дают простой воспроизводимый baseline.

### 4. Literal policy v1 до lexical candidate limit

Парные одиночные backticks выделяют непустой fragment без изменения внутренних пробелов/регистра; незакрытый backtick считается обычной пунктуацией. Quoted spans маскируются перед unquoted extraction. Для внекавычечного текста распознаются IP literals (IPv4/IPv6 через standard-library validation), POSIX absolute/relative paths и Windows drive/UNC paths, а также имена с дефисом с буквенно-цифровыми компонентами. Overlapping unquoted matches выбирают целое наиболее длинное значение, чтобы путь не учитывался ещё и как вложенное имя. Общие слова без технического признака не получают literal priority.

Extraction сохраняет буквальное написание: IP не canonicalize, path не resolve, identifier не casefold. Внекавычечные prose separators и окружающие quotes отделяются от значения. Если технический текст содержит пробелы/неоднозначную пунктуацию, пользователь может указать его в backticks; никакие значения не угадываются.

Существующих `StoredChunk.document.markdown`, `segments` и `source_ranges` достаточно: `parse_output` проверяет document hash, границы каждого source segment, равенство source_ranges этим ranges и search_text последовательности source/generated slices. Новые поля, schema version или mapping offsets в search_text не требуются.

Match ищется в original Markdown slices, заданных source segments chunk; смежные/перекрывающиеся source intervals можно объединять, несмежные — нельзя. Offsets — Unicode code points, как Python str indexing: start включительно, end исключительно. Для interval `[s, e)` и локального match `[a, b)` возвращается `[s+a, s+b)` с проверкой `document.markdown[s+a:s+b] == literal`; CRLF, Unicode normalization и регистр не преобразуются. Generated prefix и повторный overlap не смещают эти offsets; одинаковые исходные occurrences при overlap дедуплицируются.

Для typed IP/path/identifier соседние буквы/цифры, underscore и допустимые символы продолжения соответствующего значения исключают match; suffix `.bak`, дополнительная цифра IP или буквы в `route-planner` не подходят. Границы проверяются по **полному original Markdown**, включая соседние символы за пределами source interval: разрезанный chunk не превращает prefix более длинного identifier в exact match. Всё вхождение при этом должно целиком принадлежать непрерывному source-backed interval chunk. Quoted single technical token получает те же boundaries; quoted command/multitoken fragment проверяется целиком как буквальный substring. Вернуть original source offsets и kind, distinct literal count считать один раз независимо от количества occurrences. Generated title/header может влиять на FTS, но не создаёт exact source match.

Для небольшого inventory прочитать все BM25 matches и выполнить literal scan всех chunks. Объединить оба набора по ID и отсортировать:

1. Есть source-backed literal match — сначала.
2. Больше различных совпавших literals — раньше.
3. Есть BM25 match — раньше отсутствующего; raw BM25 ascending.
4. Chunk ID ascending для ties.

Только после этого брать lexical top-k. Literal-only match имеет `bm25_score=null`; literal details содержат ranges, а не выдуманный score. Дополнительный post-fusion literal boost не добавляется. Выделение границ и adversarial похожие literals проверяются отдельными unit fixtures, не через изменение frozen corpus.

Альтернатива — raw substring в search_text после initial BM25 top10 — теряет нужные chunks и принимает части похожих identifiers/generated text.

### 5. Hybrid composition и отдельный публичный режим

`app/app/hybrid_retrieval.py` предоставляет context-managed `HybridIndex(path, encoder, settings)` и `search(question, k=None)`. Он использует semantic loader/ranking через общий validated handle; arithmetic/order semantic branch сохраняется. Для pure semantic `retrieval.py` signature, default 10, `SearchResult` и JSON остаются прежними.

Hybrid defaults из SPEC: semantic_k=10, lexical_k=10, rrf_constant=60, final_k=6. `RetrievalSettings` и отдельный loader в `config.py` читают `RETRIEVAL_SEMANTIC_CANDIDATES`, `RETRIEVAL_LEXICAL_CANDIDATES`, `RETRIEVAL_RRF_CONSTANT`, `RETRIEVAL_TOP_K`. CLI overrides имеют приоритет. Положительные integer settings проверяются до `LocalEncoder` inference; loader не вызывается HTTP startup. Небольшие дополнения `.env.example`/Compose environment допустимы в apply, чтобы настройки работали в контейнере; это административная настройка без изменений HTTP flow.

RRF считает сумму reciprocal branch ranks по unique ID. Отсутствующая ветка даёт 0 contribution; valid empty lexical list не является ошибкой. Sort — score descending, chunk ID ascending, затем final limit. Кандидаты одной страницы не сливаются, из-за k выше union size дополнительные веточные candidates не запрашиваются. Typed `HybridResult` хранит общий score и optional semantic rank/cosine, lexical rank/BM25/literal matches; serializer использует общий provenance без изменения source/generated distinctions. Ошибки любой ветки не превращаются в fallback.

Пустой inventory означает **ноль chunks** в валидном полном snapshot, а не отсутствие/повреждение индекса или только отсутствие lexical matches. После проверки settings/effective k и snapshot identities/extensions semantic branch выполняет обычный `encoder.encode_query(question)`, как существующий `SemanticIndex.search`: проверяются тип/непустота вопроса, полный 512-token budget и штатный embedding runtime. Empty inventory не освобождает от assets/inference checks и не требует нового bypass path. При успешном encode обе ветки дают ноль кандидатов, RRF union пуст, API возвращает `()`, CLI — `[]` с exit code 0. Invalid question/k/settings, overflow, missing/corrupt assets и index/branch failures дают прежние контролируемые ошибки и при пустом inventory.

Raw weighted score fusion отвергнута из-за разных scales. Reranker и global literal override нарушили бы начальную схему SPEC и требуют отдельного решения после измерений.

### 6. Административные entry points

Новые команды из `app/`:

```sh
python -m app.lexical_storage build --input /data/semantic-live.db --output /data/hybrid-live.db
python -m app.lexical_retrieval query --index /data/hybrid-live.db --question 'Как настроить route-plan?' --top-k 10
python -m app.hybrid_retrieval query --index /data/hybrid-live.db --question 'Как настроить сервер?' --top-k 6 --semantic-candidates 10 --lexical-candidates 10 --rrf-constant 60
python -m app.hybrid_retrieval evaluate --questions /data/eval/questions.yaml --manifest /data/eval/manifest.json --snapshot /data/eval/1/wiki-documents.json --index /data/hybrid-live.db --fixtures /data/eval/fixtures/wiki-documents.json --synthetic-index /data/hybrid-synthetic.db
```

Hybrid query/evaluate поддерживают прежний `--model-path` override. Build поддерживает `--model-path` только как protection path, без загрузки assets. Документация даёт Compose counterparts через `docker compose run --rm --no-deps app ...` и отдельные offline-container examples. Existing semantic query/evaluate остаются доступны.

Безопасные error categories: lexical capability/schema/version/coverage/content/postings/query/k/path/build и hybrid configuration/identity/branch. `argparse.error` также не печатает значений пользователя. JSON query — явная выдача поискового текста/provenance, diagnostics — только category. Build summary содержит counts/identity. Lexical mode не импортирует heavy runtime; new modules lazy-load semantic parts только для build/hybrid.

### 7. Общий evaluation adapter без изменения protocol v1

Заменить зависимость reusable evaluator от конкретного `SemanticIndex` на минимальный typed search protocol/result protocol (`snapshot`, `chunks`, `search`, result `rank`/`chunk`; optional score в typed diagnostic payload). `protocol_input`, `covers`, `evidence_hit`, corpus validation и denominators не менять. Передавать mode/runtime metadata отдельно, чтобы lexical adapter не требовал `encoder.settings`. Существующий semantic evaluate report сохраняет свои поля/значения.

Hit@5 использует исключительно первые пять ranked results (`results[:5]` в текущем `evidence_hit`), независимо от hybrid default final_k=6 или большего значения. Evaluation явно вызывает `search(question, 5)`; evidence guard сохраняет slice даже если adapter вернул больше результатов. Добавить regression test с шестью ranked chunks при hybrid defaults: обязательный evidence только в шестом — miss, перенос того же evidence на пятое место — hit; для составного evidence недостающий span в шестом тоже не учитывается. Это проверяет границу метрики, не меняя default query top-k и protocol v1.

Новый hybrid evaluate entry point формирует отдельный comparison report schema v1 с semantic, lexical, hybrid subreports; `protocol_version` evidence остаётся 1. Все три режима используют тот же расширенный файл и его embeddings, exact source inventory и fixed chunk settings. Для каждой namespace запускать методы на согласованном поколении. File hashes до/после охватывают corpus, references и index. Case transitions (`semantic miss → hybrid hit` и регрессии) рассчитываются по стабильным IDs, никаких questions/source texts в diagnostics.

Сначала фиксировать defaults и при необходимости подбирать допустимые параметры только по tuning. Новый evaluation поддерживает `--split tuning|holdout|all` (default all); report фиксирует requested split и effective settings. Отфильтровать case execution до поиска, сохраняя validation полного corpus. Freeze выбранной конфигурации предшествует final holdout run. Исторически известные baseline holdout counts раскрываются; новый holdout не используется как очередной tuning цикл.

Главная live single-question Hit@5 — total live single-question hits / total live single-question count по tuning+holdout; показать оба split и follow-up отдельно, как в protocol v1. Synthetic, refuse/clarify и follow-up не входят в этот denominator. Достижение 90% фиксируется **после измерений**, без округления для acceptance. Follow-up quality остаётся видимой отдельной метрикой и не маскирует main score. Недостижение оставляет quality acceptance незавершённым; measured misses оформляются как ограничение и основание для отдельного следующего решения.

Решение владельца от 2026-10-09: техническое завершение требует выполненных implementation/regression/server checks, воспроизводимых measurements и сохранённой диагностики; достижение ≥90% не является условием архивирования этого технического change. Актуальная задача 5.5 фиксирует провал и передачу quality acceptance следующему этапу, не заявляет исторический критерий выполненным. [Диагностика](../../../../docs/lexical-and-hybrid-retrieval-diagnostics.md) показывает наличие всех нужных chunks и минимум шесть для q03, что делает его полный Hit@5 структурно невозможным на текущем snapshot. Улучшения recall, терминов, границ и ранжирования требуют нового proposal/design; этот decision не меняет retrieval, frozen expectations или baseline и не допускает tuning по раскрытому holdout.

Первый запуск включает lazy model load; report помечает cold/warm timings. Peak memory измеряется в отдельных процессах по режимам, чтобы сравнение lexical memory не наследовало уже загруженный E5; merged comparison связывает subreports одинаковыми fingerprints/settings/environment. Development и target Linux/Docker измерения показываются раздельно. Повторный фиксированный запуск проверяет ranking/counts, но не равенство performance numbers. Старый baseline файл не перезаписывается.

### 8. Verification scope

Первыми запускаются новые lexical storage/query/CLI tests: real sqlite3 FTS5, повторный reopen, base corruption, ID/content/postings corruption, empty inventory, stale chunks, failure preservation, aliases, quote/operator inputs, Russian case folding, IP/path/name boundaries и exact literal за initial top10. Никакие mocks BM25 не заменяют FTS integration checks.

Hybrid tests используют известные branch rankings/vectors для точной RRF arithmetic, tie/union limits и failures; отдельные integration tests используют реальный FTS и подменяют только дорогой encoder. Проверка file replacement тестирует consistency поколения. Затем existing semantic/storage/evaluation/config/health tests подтверждают обратную совместимость, fresh process с blocked heavy imports подтверждает lexical/health isolation. Typing запускается для затронутых модулей без suppressions.

Полный suite оправдан лишь после targeted checks: изменение общего reader и evaluator потенциально затрагивает несколько компонентов. После этого — offline real-E5 evaluation frozen live/synthetic snapshots, повторение и отдельная target-server acceptance с runtime network disabled. Tests доказывают корректность реализации, а measurement отдельно проверяет quality threshold.

## Risks / Trade-offs

- [unicode61 не учитывает русскую морфологию] → semantic branch дополняет lexical; tuning/evidence misses измеряются без внедрения stemmer в этом этапе.
- [OR по общим словам даёт шум; буквальные matches не гарантируют ответ] → BM25 + RRF, explicit score kinds, source evidence acceptance без answerability threshold.
- [Boundary extraction может пропускать неоднозначные команды/paths] → backticks для полного fragment, typed boundary fixtures и versioned policy без value guessing.
- [Read-only FTS validation копирует файл в память] → ограниченный текущий inventory; one-time index initialization, освобождение clone, отдельные startup/peak memory measurements.
- [Runtime SQLite может не поддерживать FTS5 или отличаться между Windows/Docker] → capability probe при административной операции, identity в reports и реальные offline Docker checks без runtime extension download.
- [10/10/60 может не дать Hit@5 ≥90% при нынешнем chunking] → честная quality acceptance и miss report; tuning только разрешённых параметров, дальнейшее изменение scope отдельно.
- [Holdout уже доступен в baseline] → явно записать историческую exposure и зафиксировать configuration до новых holdout measurements; не заявлять blind generalization.
- [Retained reader мешает Windows file replacement] → явное закрытие index/context manager и сохранение прежнего output при publication failure; orchestration остаётся следующим этапом.

## Migration Plan

1. Сохранить прежние semantic snapshots и baseline. Установленные зависимости/assets не менять; проверить FTS5 capability в текущем Python и целевом образе.
2. Собрать `/data/hybrid-live.db` и `/data/hybrid-synthetic.db` отдельными outputs из текущих semantic файлов. Проверить lossless reopen и file hashes input.
3. Выполнить lexical/hybrid query и tuning-only comparison, зафиксировать settings, затем final frozen comparison/holdout в offline процессах. Сохранить отдельный report в `docs/` и явно указать status качества.
4. На целевом сервере повторить проверку в заранее собранном Docker image с сетью, отключённой на runtime; записать timings, memory, source hashes и влияние на Wiki.js отдельно от development результатов.
5. Выбирать новый файл только для явно вызываемых lexical/hybrid CLI/API. Rollback возвращает прежний semantic режим/файл и configuration; in-place migration и изменение HTTP startup не нужны.
