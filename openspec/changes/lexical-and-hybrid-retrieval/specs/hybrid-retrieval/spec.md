# Spec Delta

## Purpose

Объединять semantic similarity и lexical relevance в детерминированный набор chunks одного локального snapshot и воспроизводимо измерять качество относительно чистого semantic retrieval на frozen evaluation corpus.

## ADDED Requirements

### Requirement: Consistent hybrid branches
Hybrid search SHALL выполнять semantic и lexical поиск по одному полностью проверенному snapshot с одним source namespace, inventory и provenance. Identity модели, tokenizer/input format, semantic vectors и lexical policies SHALL валидироваться до выдачи результатов; две ветки SHALL NOT использовать разные поколения файлов или разных источников. Semantic branch SHALL сохранять локальный CPU E5 inference, question-only input, 512-token limit и отказ от truncation. Обычный hybrid search SHALL передавать обеим веткам только supplied question без истории или rewriting. Missing/incompatible/corrupt branch SHALL завершать весь hybrid request контролируемой ошибкой без молчаливого fallback; успешно выполненная lexical branch с нулём совпадений SHALL быть допустима. Пустой inventory SHALL возвращать пустую выдачу после question/configuration validation. Индекс SHALL оставаться read-only при query, включая замену файла другим административным процессом.

#### Scenario: Consistent snapshot during file replacement
- **WHEN** между загрузкой semantic vectors и lexical search опубликован другой файл по тому же пути
- **THEN** обе ветки текущего request используют одно исходное поколение либо request отклоняется явно; mixed generation results не возвращаются

#### Scenario: Missing incompatible or failed branch
- **WHEN** отсутствует FTS extension, повреждён vector, identity отличается или одна из веток завершилась ошибкой
- **THEN** hybrid search возвращает контролируемую ошибку, не выдаёт одноветочный fallback и не изменяет файл

#### Scenario: No lexical matches
- **WHEN** вопрос валиден, semantic candidates существуют, а lexical branch успешно возвращает пустой список
- **THEN** fusion использует semantic candidates с одноветочным RRF contribution

#### Scenario: Empty valid inventory
- **WHEN** полностью совместимый snapshot содержит ноль chunks, settings/effective k валидны и обычная semantic query validation/inference успешно выполняется для supplied question
- **THEN** обе ветки и RRF union пусты, API возвращает пустую выдачу, query CLI возвращает `[]` с exit code 0; final top-k=6 не создаёт искусственных результатов

#### Scenario: Empty inventory does not bypass validation
- **WHEN** inventory содержит ноль chunks, но question пуст/неверного типа, query превышает 512 tokens, k/settings неверны, model assets отсутствуют/повреждены либо snapshot/branch несовместим
- **THEN** request завершается штатной контролируемой ошибкой; пустой inventory SHALL NOT обходить question/budget/model/index validation или inference failures

### Requirement: Deterministic reciprocal rank fusion
Система SHALL объединять semantic и lexical candidate lists через RRF: score(chunk) = сумма `1 / (rrf_constant + branch_rank)` по веткам, где присутствует chunk, с rank начиная с 1. Defaults SHALL быть semantic candidates=10, lexical candidates=10, rrf_constant=60 и final top-k=6. Raw cosine и BM25 SHALL NOT складываться или нормализоваться друг к другу; literal priority SHALL влиять на lexical rank до RRF без отдельного post-fusion boost. Каждый chunk SHALL встречаться в final list один раз по chunk ID в пределах одного snapshot, сохраняя разные chunks одной страницы. Final order SHALL быть RRF score по убыванию, при равенстве chunk ID по возрастанию; final rank SHALL начинаться с 1. Top-k выше union size SHALL возвращать весь union без добора из кандидатов за пределами branch limits.

#### Scenario: Known branch rankings and overlap
- **WHEN** chunk имеет semantic rank 2 и lexical rank 3 при константе 60
- **THEN** его score равен `1/62 + 1/63`, chunk возвращается один раз и сохраняет оба branch ranks

#### Scenario: Ties and single-branch candidates
- **WHEN** union содержит одинаковые RRF scores, chunk только одной ветки и несколько chunks одной страницы
- **THEN** ties разрешаются по chunk ID, missing branch не даёт contribution, отдельные chunks страницы сохраняются

#### Scenario: Final limit and literal priority
- **WHEN** exact literal поднят на первое место lexical list, а final k превышает число уникальных branch candidates
- **THEN** RRF использует новый lexical rank и возвращает только union, без глобального exact-match override и дополнительного добора

### Requirement: Explicit retrieval settings and hybrid output
Система SHALL предоставлять typed settings и CLI overrides для branch candidate counts, RRF constant и final top-k. Все значения SHALL быть положительными целыми; bool, ноль, отрицательные и нецелые значения SHALL отклоняться до inference. Hybrid query SHALL возвращать rank, finite RRF score, chunk ID, semantic/lexical ranks и их scores либо явные null для отсутствующей ветки, literal match evidence и исходный provenance. Output SHALL различать BM25, cosine и RRF score; эти значения SHALL NOT заявляться вероятностью ответа или достаточностью evidence. Новые административные команды SHALL иметь документированные app/ и Compose примеры; существующий pure semantic API/CLI SHALL сохранять default k=10, формат JSON, ranking и ошибки. HTTP startup/health SHALL оставаться независимыми от retrieval configuration/model/index. Errors SHALL NOT раскрывать credentials, question, source text или raw backend exception.

#### Scenario: Defaults overrides and invalid settings
- **WHEN** hybrid query выполняется без overrides, с валидными overrides или с invalid setting
- **THEN** применяются соответственно defaults 10/10/60/6, явно заданные параметры либо контролируемая ошибка до inference

#### Scenario: Search result remains citable
- **WHEN** найден chunk таблицы или code continuation
- **THEN** final result содержит исходные ranges, URL/source identity и continuation metadata, а generated segments остаются отличимыми от исходных цитат

#### Scenario: Pure semantic compatibility
- **WHEN** прежний semantic API/CLI вызывается после добавления hybrid режима
- **THEN** он возвращает прежний cosine ranking/JSON с default k=10 без lexical/RRF behavior

### Requirement: Frozen three-mode comparison
Система SHALL сравнивать semantic-only, lexical-only и hybrid на одних frozen questions/reference/chunks/embeddings, с сохранением байтов corpus, reference, splits и прежнего baseline. Evidence Hit@5 SHALL использовать существующий protocol v1: полное покрытие всех обязательных source ranges совокупностью top 5 chunks, с проверкой source namespace; page hit, generated text и частичное composite evidence SHALL NOT считаться полным hit. Live/synthetic × tuning/holdout SHALL показываться раздельно; single-question и follow-up SHALL иметь отдельные counts/hits/misses/Hit@5, empty denominator SHALL давать null. Только evaluation adapter SHALL составлять `previous_question + "\n" + current_question` без ответов, одинаково для всех режимов. Semantic/hybrid budget overflow SHALL давать ошибку без shortening. Refuse/clarify SHALL показываться отдельно от answerable denominator. Report SHALL содержать modes/parameters/policy versions, corpus/reference/index/model fingerprints, SQLite/runtime/environment identity, case IDs/rankings, hits/misses, per-query latency и process peak memory с явным указанием методики. Repeated runs на той же среде SHALL давать одинаковые ranks/scores/counts; latency/memory SHALL NOT требовать побайтового равенства.

#### Scenario: Comparable three-mode report
- **WHEN** все три режима выполняются на одном frozen corpus и соответствующих live/synthetic extended snapshots
- **THEN** отчёт позволяет сравнить Hit@5 и case transitions по одинаковым группам, содержит fingerprints и параметры, а inputs и прежний baseline остаются неизменными

#### Scenario: Composite source coverage
- **WHEN** top 5 покрывает только часть обязательных spans, только generated header или похожий источник другого namespace
- **THEN** case считается miss во всех режимах независимо от совпадения страницы

#### Scenario: Sixth chunk cannot satisfy Hit at five
- **WHEN** при hybrid default final top-k=6 обязательный evidence находится только в шестом ranked chunk, либо шестой chunk единственный покрывает недостающий обязательный span составного evidence
- **THEN** Hit@5 SHALL учитывать только первые пять chunks и считать case miss; перенос последнего необходимого evidence на пятое место SHALL давать hit при полном покрытии остальных spans, независимо от размера возвращённой выдачи

#### Scenario: Follow-up and answerless cases
- **WHEN** corpus содержит follow-up, refuse, clarify и synthetic cases
- **THEN** follow-up использует protocol v1 и отдельную метрику, refuse/clarify не входят в denominator, synthetic не улучшает live Hit@5

### Requirement: Measured quality acceptance and tuning discipline
Параметры SHALL подбираться только по tuning cases; финальная конфигурация SHALL фиксироваться до нового измерения holdout. Report SHALL раскрывать, что holdout уже измерялся в прежнем semantic baseline, и SHALL NOT представлять его как впервые увиденный набор. Основная live single-question Hit@5 SHALL рассчитываться из суммарных hits/counts tuning и holdout этой группы с обязательным отдельным показом каждого split; follow-up SHALL оцениваться отдельно по protocol v1. Целевой порог hybrid live Hit@5 ≥90% SHALL проверяться измерениями, как предусматривает этап 4 SPEC; достигнутое/недостигнутое состояние SHALL указываться явно. Если порог не достигнут, технически работающий поиск SHALL NOT заявляться как прошедший quality acceptance или завершивший retrieval критерий MVP; отчёт SHALL перечислять misses и ограничение. Низкое качество SHALL NOT автоматически разрешать изменения frozen corpus, chunking, reranker или модели в этом change. Этот этап SHALL NOT добавлять answer generation или runtime follow-up resolution.

#### Scenario: Target remains unmet
- **WHEN** hybrid измерение даёт live Hit@5 ниже 90%
- **THEN** отчёт фиксирует недостигнутый критерий и miss IDs без изменения expectations/denominator или заявления о прохождении quality acceptance

#### Scenario: Holdout protection
- **WHEN** tuning использован для выбора параметров и затем измеряется holdout
- **THEN** отчёт фиксирует выбранную конфигурацию и историческую доступность baseline holdout; новые holdout misses не используются для следующего подбора в этом эксперименте
