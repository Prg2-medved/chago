# Design

## Context

Current owner disposition, 2026-10-20: **v2 ended negatively; reranker rejected;
no additional runs**. Protocol v2 and acceptance criteria remain unchanged.
The design below preserves the historical experiment, not accepted reranker
behavior. Proposed administrative completion: standard archive without spec
sync, retaining eight unfinished tasks. No archive is performed now.

Мотивация — в [proposal.md](proposal.md). Первоначальный propose не запускал inference; последующий development v1 завершил все 36 preregistered комбинаций с максимумом 6/9 и stop condition 5.2 (`docs/retrieval-quality-result.md`). Planning revision 2026-10-16 расширяет только следующий final-ranking experiment; reranker ещё не реализован, модель не скачана, новые эксперименты и приёмка не выполнены. Разделы 3–4 описывают закрытую фазу v1, раздел 4a — единственное разрешённое продолжение, без переписывания истории.

Исходная реализация до development v1 (историческое основание packing/literal экспериментов):

- `app/app/chunking.py::chunk_document` перед каждым помещающимся code/table вызывает `flush()` и выдаёт блок отдельно. Поэтому короткое пояснение и команда могут занимать разные chunks. Algorithm version участвует в chunk identity. Структура chunk уже поддерживает source/generated segments и continuation metadata.
- `lexical_retrieval.py` использует unicode61/BM25 и source-backed literal priority. `_NAME` распознаёт имена с дефисом, но не underscore identifiers. Unicode61 не решает морфологию. Существующий spec явно запрещает morphological expansion, synonyms и rewriting.
- `hybrid_retrieval.py` использует один read-only snapshot и обычный RRF; доступные positive-integer overrides достаточны для исследования candidate limits без новой архитектуры.
- `retrieval_evaluation.py` уже проверяет идентичность полного reference inventory и source ranges, берёт только `results[:5]`; настройки chunks фиксированы 350/450/50/512. Эти числовые настройки сохраняются. `retrieval_comparison.py` даёт separate mode workers, fingerprints, split selection, повторяемость и latency/memory.
- Исторический snapshot: 24 страницы, 910 chunks, выбранные settings 10/1/60/6; API defaults 10/10/60/6. Измерения сервера: hybrid RSS около 1.12 GB, 4 CPU/5 GiB container; это данные предыдущего этапа, не стоимость будущего rebuild.

## Goals / Non-Goals

**Goals:** проверить минимальные общие изменения с причинной диагностикой; получить воспроизводимые ≥11/12 на frozen v1 и отдельную честную независимую проверку; сохранить provenance, budgets и воспроизводимость legacy поведения.

**Non-Goals:** устранить любой miss любой ценой; считать source coverage доказательством retrieval; вводить page-sized chunks, виртуальное объединение шести результатов в один, замену E5, stemming, thesaurus или LLM rewriting. V2 допускает ровно один явно выбранный CPU cross-encoder поверх legacy union; обучение, quantization, перебор моделей, изменение inventory/literals и повторный поиск candidate limits исключены.

## Decisions

### 1. Сначала зафиксировать разрешённые данные и критерии выбора

До изменения retrieval/chunking и запуска кандидатов создать отдельный versioned experiment protocol с fingerprint, датой фиксации, перечнем допустимых данных, сеткой, selection rule, resource gates и описанием роли независимого evaluator. Это первый обязательный implementation gate (task 1.1). Назначение evaluator, подготовка и integrity validation закрытого package (tasks 1.2–1.3) могут идти параллельно development tasks 2–5 и не являются их prerequisites. Отсутствие evaluator/package блокирует independent acceptance, но не development или предшествующие финальные проверки.

| Данные | Разрешённое использование | Запрещённое использование |
| --- | --- | --- |
| Frozen live tuning: 9 single-question answerable + отдельный follow-up | Диагностика, ablation, выбор из объявленной сетки | Изменение evidence/expectations |
| Исторический holdout, включая q04/q08/q18 | Один финальный comparison выбранного решения; legacy regression report | Выбор policy, новых synonyms, параметров, tie-break или следующей итерации |
| Исходный Markdown | Общая структурная упаковка и integrity checks без привязки к оценочным IDs | Правила по page IDs, путям, offsets, тексту конкретного holdout вопроса |
| Новое закрытое validation package | Однократная независимая приёмка после lock, успешных frozen v1 и target-server acceptance | Tuning и выбор между кандидатами; вскрытие/запуск при провале предшествующего gate |

Знание исторической диагностики нельзя отменить: протокол раскрывает этот факт. Она обосновывает необходимость независимой оценки, но не создаёт development cases из holdout misses. Нельзя генерировать их парафразы или использовать q04/q08/q18 как targeted acceptance tests. Общие synthetic unit tests для provenance/структурных свойств допустимы и не доказывают live качество.

Новый package готовит отдельный evaluator/владелец документации, не выбирающий policies/configuration и не использующий historical miss list как план вопросов. Это организационная роль, не новый сервис и не поручение субагенту в этом propose. Package хранится вне доступного разработчику tuning каталога; evaluator фиксирует hashes до первого запуска. Нужны ≥20 новых answerable live single-question случаев из frozen reference, с обычным prose, командами, таблицами, identifiers и composite evidence; не дубликаты/парафразы старых вопросов и не synthetic подмена. Отдельно ≥2 follow-up и ≥3 refuse/clarify для регрессионного отчёта; они не входят в основной denominator. Evidence вручную сверяется до retrieval, спорные вопросы разрешаются до freeze.

Использовать существующий формат package/validator и те же source identity/coverage semantics, отдельные questions/manifest/report. ≥20 закрытых single-question cases маркируются holdout; необходимые validator tuning cases хранятся отдельно внутри package и не входят в independent denominator. Для independent запуска использовать только `--split holdout`. Остальное обязательное coverage существующего validator также сохраняется; при необходимости используются явно отдельные synthetic edge cases. Frozen v1 не переписывается. Этот package независимо проверяет новые вопросы на том же корпусе, а не перенос на неизвестные документы. При ≥20 случаях порог — ceil(0.9*N), отдельно показать числитель/знаменатель и 95% Wilson interval: observed 90% не означает статистически доказанную population accuracy ≥90%.

До вскрытия validation фиксируются code revision, artifacts/model/tokenizer hashes, policies и settings выбранного решения; затем последовательно проходят frozen v1 и target-server acceptance. Только после успеха обоих gates и всех обязательных integrity/regression/resource checks evaluator вскрывает и запускает закрытый package. При провале или незавершённости предшествующего обязательного gate package сохраняется закрытым и не расходуется. Повторный идентичный запуск для воспроизводимости разрешён; смена решения после просмотра validation запрещена. Провал validation оставляет independent acceptance открытым; будущая итерация требует нового закрытого package и пересмотра experiment protocol. Если evaluator/package недоступны, development tasks 2–5 могут выполняться и завершиться, но независимую приёмку нельзя заявлять.

### 2. Разделить достижимость, recall и ranking

Для tuning вычислять минимальное число реально существующих chunks, покрывающих все обязательные spans (точный minimum set cover по объединению исходных ranges; overlap допустим, generated text не участвует), и сохранять witness IDs/ranges. Ограничивать поиск chunks, пересекающими evidence; если вычисление minimum не завершено, показывать unknown и проверенные bounds, не заявлять точный oracle. Проверка полного inventory отделяет отсутствующий evidence от структурного ограничения; та же проверка branch union — candidate loss, final top-5 — ranking loss. При невозможности cover показывать причину, не произвольный minimum. Для финальных отчётов аналогичная диагностика остальных splits допускается лишь после lock, без обратного tuning.

Frozen v1: single-question denominator 12 = 9 tuning + 3 holdout. Follow-up 1+1 даёт исторические 14 answerable live, но не входит в основной denominator protocol v1. Требуется ≥11/12 = 91.67%; 10/12 = 83.33% недостаточно. Нужен чистый прирост минимум пяти hits: потеря прежнего hit требует дополнительного нового hit и фиксируется в transitions, а не запрещается отдельно. Даже идеальный tuning 9/9 при прежнем holdout 0/3 дал бы только 75%; нужны минимум 2/3 holdout, а при tuning 8/9 — все 3/3.

Для q03 минимум 6 означает невозможность именно его полного Hit@5 на старом inventory. Верхняя граница aggregate при единственном структурно невозможном case — 11/12, так что q03 сам по себе НЕ доказывает невозможность порога 90%. Оставлять q03 единственным miss теоретически допустимо по метрике; это крайне хрупкий путь, требующий успеха всех остальных случаев. План явно исследует устранение структурной границы q03, не ослабляя его expectations.

### 3. Один кандидат структурной упаковки — development v1, завершён

Предложенная policy `markdown-chunking-2`: перед выдачей целого короткого fenced code проверить совместную упаковку непосредственно предшествующего pending prose в том же heading path. Если объединение сохраняет body ≤450 и полный E5 input ≤512, выдать единый chunk с исходными segments и code structure metadata. Target 350 остаётся ориентиром. При недостаточном budget или смене heading/page — прежнее разбиение. Целые tables и длинные code continuations не менять. Не добавлять новый overlap, склейку разделов, summaries или дополнительный parent index.

Кандидат обоснован наблюдаемым `flush()` и q03 tuning boundary 6579. На реальном tokenizer требуется проверить, что `[6504,6579)` и `[6579,6595)` действительно оказываются вместе, бюджеты соблюдены и новый minimum q03 ≤5. Это необходимые проверки выбранного структурного направления; остальные четыре evidence части всё ещё надо найти и ранжировать. Если пара не помещается или heading paths различаются, не ослаблять лимиты и не придумывать специальный join: зафиксировать отрицательный результат и остановить эту ветку до review плана.

Альтернатива «увеличить final k до 6» отвергнута: scorer остаётся @5. Увеличение body/input limit нарушает E5 contract. Page aggregation меняет единицу измерения и ухудшает управляемость контекста. Новая policy не обязана решать длинный JSON или общий vocabulary gap; их успех нельзя обещать без измерений.

### 4. Один кандидат literal policy и небольшая сетка — development v1, завершена

Дополнительная policy v2 распознаёт полные явно заданные identifiers с underscore (`charge_device_id`, `clear_device_id`), сохраняя существующие quoted/IP/path/hyphen правила, case sensitivity, longest non-overlapping extraction и границы полного значения в original Markdown. Literal evidence только в title/heading/generated text не получает exact priority. Это исправляет наблюдаемый tuning q07 extraction gap без словарей и зависимостей.

Версия выбирается явно при build и хранится в lexical metadata; query dispatch поддерживает v1/v2. Старые snapshots исполняют v1, unknown version отклоняется. Политика v2 не меняет FTS content/tokenizer, BM25 и RRF contract; rebuild lexical extension не пересчитывает embeddings. При изменении chunks embeddings пересчитываются полностью для нового inventory; перенос vectors по старым IDs запрещён.

После preregistration проверить 2 chunk policies × 2 literal policies × S={10,40,120} × L={1,10,20}, RRF=60, query default k=6, scorer k=5: максимум 36 комбинаций. S120 включает исторический tuning q02 S112 без поиска произвольной огромной сетки; q02 lexical gap сам по себе этим не решается. Выбор: максимальные полные tuning single-question hits, затем предпочтение варианту без потери прежних tuning hits, затем follow-up hits, затем меньше изменённых policies, затем меньшая сумма branch limits и меньший S. Потеря отдельных legacy tuning hits обязательно фиксируется по IDs, но не является исключающим gate: при большем итоговом числе hits кандидат с такими потерями допустим. Если при равном итоговом качестве все варианты имеют потери, этот tie-break их не различает и применяется следующий. Финальный residual tie — стабильное лексикографическое сравнение policy IDs. Нарушения обязательных integrity/resource и функциональных regression checks (совместимость, budgets, provenance, legacy policy reproduction) исключают кандидата; case-level tuning hit→miss transitions учитываются только как отчёт и tie-break.

Показать ablation относительно 10/1/60 на старом inventory: limits-only, packing-only, literals-only, совместный вариант. Все три retrieval режима для выбранного inventory оцениваются на одинаковых chunks/embeddings; сравнение разных inventories маркируется отдельно. API defaults остаются 10/10/60/6; выбранный experiment settings file используется явно. RRF formula, no post-fusion boost и question-only search сохраняются. Если лучший допустимый вариант даёт tuning <8/9, верхняя граница frozen aggregate даже при 3/3 holdout <11/12: остановить этап с отрицательным development результатом до вскрытия новых validation данных, запросив review расширения плана.

Альтернативы: только L20 уже давал q07 hit с aggregate regressions, одной RRF constant недостаточно для отсутствующих candidates, synonyms/morphology по раскрытым holdout вопросам нарушили бы discipline. Если разрешённые данные показывают недостаточность набора, фиксировать предел и выносить расширение на review, не добавлять скрыто model/reranker/expansion.

### 4a. Один CPU cross-encoder после stop condition v1

**Минимальность candidate union.** Сохранённый tuning report `data/retrieval-quality-improvement/grid/c1-l1-s120-l1.json` показывает полное branch-union coverage q02 (minimum=3) и q07 (minimum=1), оба с final-ranking loss. S=120 — наименьший уже проверенный semantic limit сетки v1 с нужным покрытием; это не доказательство глобального минимума и не разрешение искать промежуточные limits. Поэтому фиксируются legacy chunking/literal v1, прежний read-only `data/hybrid-live.db`, S=120/L=1, максимум 121 уникальный chunk. L=20 и literal v2 не нужны для recall этих случаев и добавили бы переменные. Полный union передаётся reranker до RRF top-k cutoff; никакого выбора candidates по expectations, page quota, neighbours или boosts. Векторы и индекс не перестраиваются.

**Механизм и альтернатива без модели.** RRF использует ranks, теряя score margins и содержание пары question–chunk. Изменение весов/использование cosine и literal metadata дешевле, но существующая диагностика не устанавливает общее правило, которое поднимет одновременно три q02 evidence chunks и сохранит остальные hits. Это не доказательство невозможности немодельного решения. Один cross-encoder добавляет совместную оценку текста вопроса и passage; достаточность для составного evidence неизвестна. Ни улучшение отдельного chunk rank, ни page hit не заменяют полный Hit@5.

**Один artifact.** Выбран `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, immutable revision `1427fd652930e4ba29e8149678df786c240d8825`, только FP32 `model.safetensors`. [Model card](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1/blob/1427fd652930e4ba29e8149678df786c240d8825/README.md) указывает Apache-2.0 и русский; [config/revision](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1/commit/1427fd652930e4ba29e8149678df786c240d8825) фиксирует MiniLM 12 layers/384 hidden. Около 471 MB weights — умеренный дополнительный artifact для первого CPU кандидата, не оценка runtime RSS и не обещание скорости/качества на русском техническом корпусе. Стандартная классификационная архитектура использует существующие pinned torch/transformers/tokenizers, fast tokenizer и локальные assets без новых зависимостей/remote code. Не выбраны отдельная экспортная архитектура, quantized вариант или урезанный сторонний словарь: это добавило бы варианты совместимости и сравнения. Все weights/tokenizer/config hashes, published weight/tokenizer hashes и offline flags зафиксированы в protocol v2; скачивание — отдельная будущая task, не действие planning review.

**Input и scoring.** Полная пара supplied question + неизменный `StoredChunk.search_text`, без E5 prefixes, instructions, дополнительной истории/metadata или нормализации. Только evaluation adapter сохраняет прежнюю follow-up конкатенацию. Token budget по собственному pinned tokenizer: question ≤128 без special tokens; pair ≤512 с четырьмя special tokens, passage занимает остаток `508-question_tokens`. Batch=1, `padding=False`, `truncation=False`: каждая полная пара обрабатывается при фактической длине ≤512, без padding до 512. До quality inference preflight всех разрешённых tuning pairs; любой overflow останавливает experiment целиком для review, без dropping/truncation/windows/расширения budgets. Compliance E5 не доказывает compliance этого tokenizer. Existing E5/chunk budgets неизменны.

CPU FP32/eager/eval/inference mode, seed=0, deterministic algorithms, intra-op=4/inter-op=1, tokenizer parallelism off; logit — один finite raw classification score. Inference order: chunk ID ascending; final order: logit descending, затем exact tie по chunk ID. Никакого смешивания с RRF/cosine/BM25, sigmoid calibration, epsilon tie или threshold. Original chunks/ranges сохраняются, output отдельно маркирует reranker score/identity и прежние branch/RRF scores; RRF JSON/defaults не меняются.

**Protocol v2 и controls.** [Новый experiment protocol](../../../docs/retrieval-quality-experiment-protocol-v2.md) отделён от immutable protocol v1 и evidence scorer protocol v1. Перед implementation task 5.4 фиксирует hash v2, code/worktree identity, hashes защищённых inputs, v1 receipt/results и grid. Перед inference task 5.5 фиксирует проверенный bundle/runtime. Ровно три arms: legacy RRF 10/1/60/6; RRF 120/1/60/6 на том же legacy snapshot; один reranker на union второго arm. Это один experimental candidate, без повторной сетки. Historical holdout не читается/не запускается в development; synthetic/follow-up отдельно. API defaults 10/10/60/6 и pure semantic/HTTP health сохраняются. RRF-control formula/output не заменяются: reranker — явный opt-in experimental mode.

**Воспроизводимость и ресурсы.** Два свежих последовательных запуска каждого arm с first/warm passes в одинаковом порядке cases; identical union/input hashes, serialized finite scores/ranks/counts в одной среде. Версии OS/CPU/Python/container/torch/transformers/tokenizers и все model/tokenizer/settings identities сохраняются; побайтовое равенство между разными платформами не заявляется, на целевой среде выполняются собственные повторы. До lock отдельный tuning-only resource screening под i5-14400 Linux/Docker 4 CPU/5 GiB: E5 и reranker resident вместе, без concurrent baseline worker. No errors/OOM, cap, end-to-end warm mean ≤2× legacy arm 1 обязательны в обоих повторах; измерять init/first/warm, rerank cost, whole-worker peak RSS, container peak, swap/available memory и disk. Missing measurements не являются pass. Screening не заменяет final target-server acceptance; Wiki.js gate остаётся на прежнем месте после frozen gate. Порог не расширяется ради модели.

**Decision/stop.** Один candidate допускается к 5.3 lock лишь после ≥8/9 tuning и всех mandatory input/integrity/reproducibility/resource gates. Legacy q03 minimum=6 остаётся miss в denominator; для 8/9 должны пройти все остальные восемь cases, включая одновременное попадание трёх q02 chunks и одного q07 chunk в top-5. Все индивидуальные hit→miss против обоих controls, rank/partial losses и follow-up transitions фиксируются; improvement totals не скрывают потерь. При <8/9 или mandatory failure — новый отрицательный report и stop до lock/final/independent, без другого artifact, L20/literal v2 fallback или донастройки. На этом inventory потеря любого другого hit не позволит достичь development threshold, хотя отдельного case-level exclusion gate нет. ≥8/9 — лишь development gate, не обещание frozen/independent quality.

### 5. Приёмка и ресурсы

Три независимых статуса: structural feasibility (не Hit), frozen v1 quality, independent validation. Quality acceptance нового этапа требует одновременно frozen v1 ≥11/12, независимый live validation ≥90%, integrity/regression checks и реальный повторяемый target-server report. Исторический holdout явно помечается exposed, новый validation не смешивается с denominator 12 и не улучшает frozen score. Follow-up, synthetic, refuse/clarify показываются отдельно; generation/answer correctness не заявляется.

Финальная последовательность: lock → frozen v1 ≥11/12 → target-server acceptance → independent validation ≥90%. На каждом переходе обязательны успешные предшествующие gates. При frozen v1 <90% — «MVP retrieval quality unmet», последующие acceptance шаги не выполняются. При провале серверной приёмки её статус остаётся незавершённым, independent validation не запускается. При old v1 ≥90%, но failed/absent independent validation: «frozen target achieved, independent acceptance incomplete» с отдельным статусом server gate. Не закрывать quality task при таких состояниях и не расходовать закрытый package для диагностики более раннего провала.

На i5-14400/15 GiB без GPU повторить offline Linux/Docker comparison дважды при 4 CPU и 5 GiB memory cap, с matching fingerprints и одинаковыми ranks/scores/counts. V2 использует прежний read-only snapshot без chunking/embedding/FTS rebuild: соответствующие build duration, build-only RSS и build disk increment отмечаются N/A с этой причиной, не нулём и не пропуском обязательных измерений. Исторические build records v1 сохраняются отдельно. Для v2 измерить model loading/init durations, model bundle disk increment, first-query и warm latency, whole-worker peak RSS, container memory peak, swap и доступную память; те же правила N/A и измерений действуют при development screening. Resource gate: отсутствие OOM/ошибок при cap, warm mean selected hybrid ≤2× legacy hybrid в той же среде; Wiki.js ≥20 запросов до и ≥20 во время нагрузки, ноль ошибок и p95 ≤2× baseline p95. Это предложенные review-критерии; прежний server report не содержал warm latency/p95, поэтому сравнение измеряется заново, не выводится из initialization. Указать sample size, методику и ограничения короткого замера.

Рост candidate limits не увеличивает brute-force cosine inventory, но увеличивает lexical/fusion workload; v2 дополнительно измеряет reranking cost при неизменном inventory. Packing и CPU embedding rebuild относятся только к закрытой фазе v1 и в v2 не повторяются. Arms сравниваются в последовательных отдельных workers; внутри candidate worker E5 и reranker resident вместе.

## Risks / Trade-offs

- 6/12 → ≥11/12 — большой скачок → ограниченный набор исправлений не гарантирует его; quality task остаётся открытым при провале, расширение только через review.
- Исторический holdout уже известен авторам → preregistration и независимые новые вопросы уменьшают риск, но отчёт честно сохраняет disclosure.
- 20 validation cases — малый и коррелированный по страницам набор → показать uncertainty и границы обобщения; не делать population guarantee.
- Packing может разбавить embeddings, literal v2 — вытеснить prose → ablation, отчёт всех потерянных legacy tuning hits и предпочтение варианту без потерь при равном итоговом качестве; отдельный финальный regression report не используется для донастройки кандидатов.
- Новый minimum ≤5 не гарантирует recall/rank → отдельные witness/union/top-5 проверки.
- Ограниченный scope может не закрыть vocabulary gap → никаких словарей под q02 или holdout, отрицательный результат сохраняется.
- Full-input cross-encoder preflight может не пройти на другом tokenizer; 121 CPU pairs могут нарушить прежний latency gate → остановка и новый review без truncation, смены модели или ослабления порогов. Independent pointwise reranking не гарантирует покрытие всех частей q02.

## Migration Plan

1. Заморозить experiment protocol и снять hashes защищённых inputs, snapshots, baselines. Подготовку evaluator/package и validation manifest commitments вести параллельно: их отсутствие не блокирует steps 2–4 и development tasks 2–5, commitments обязательны до независимого запуска.
2. Все экспериментальные артефакты писать в отдельный `data/retrieval-quality-improvement/<variant>/`, reports — в отдельные paths; reject input/output aliases. Старые snapshots не мигрировать in-place.
3. Поддержать явный legacy/new chunking selection и lexical metadata dispatch. Базовый storage schema и числовые budgets сохраняются; неизвестные algorithm/policy versions дают безопасную ошибку. Проверить allowlists downstream readers до использования нового algorithm.
4. Для нового chunk inventory пройти chunking → storage → E5 → lexical rebuild; integrity и повторное чтение до публикации. Для literal-only варианта достаточно lexical extension rebuild копии semantic snapshot.
5. Зафиксировать выбранные artifacts/settings (lock), пройти final frozen v1, затем target-server acceptance выбранных неизменных artifacts и только после их успеха — independent validation. При провале обязательного gate остановить дальнейшую приёмку, сохранив закрытый package невскрытым и неиспользованным. Reports не перезаписывают historical baselines.
6. Для использования выбранного решения явно указать новый snapshot/settings. Rollback — прежние paths/policies/settings; defaults и HTTP startup остаются прежними. Промышленная atomic-full-reindex остаётся отдельным этапом.

После зафиксированного stop v1 steps 2–4/grid не повторяются: task 5.4 receipt v2 → 5.5 offline bundle verification → 5.6 opt-in implementation/tests/input preflight → 5.7 single tuning experiment/resource screening → 5.8 decision. Только успех 5.8 открывает 5.3 lock и прежние 6.1–6.4. V2 outputs идут в новые paths, rollback отключает opt-in reranker и возвращает legacy settings без изменения snapshots. Доступ к историческому holdout остаётся только после lock для финального отчёта; закрытый package не используется при провале любого gate.


## Actual v2 outcome, 2026-10-20

Downloaded first-run evidence supersedes pending implementation/server status
in historical planning sections. Sole candidate fails both mandatory gates:
4/9 tuning against >=8/9; warm 2.446002 s against legacy 0.009478 s
(258.071122x against <=2x). It gains q07 but loses q01/q12/q19; q02 full union
coverage does not become full top-5 coverage. Docker exit=0, no OOM/cap
violation; full-union CPU reranking dominates latency. This rejects this
candidate without claiming all rerankers fail.

Task 5.8 is complete as a negative decision. Task 5.7 remains incomplete because
second fresh repeats are absent; first/warm equality is not fresh-repeat proof.
Failed first summary blocks repeat 2 in the runbook. Stop before 5.3/6;
no holdout/independent validation/new experiment. Missing evaluator/package
also keeps 1.2-1.3 open. Final order and acceptance requirements remain unchanged.
See `docs/retrieval-quality-result-v2.md` and its linked audit.

At the owner's explicit request, result.md gains a v2 addendum; original v1
bytes remain in `docs/retrieval-quality-result-v1-frozen.md` with original SHA-256.
Existing receipts preserve the pre-addendum commitment, not a new execution
lock. Protocol v2, model, retrieval policy, thresholds and protected inputs
remain unchanged. Owner review has ended this candidate branch. The v2 report
proposes standard archive: retain unchecked tasks, acknowledge incomplete-task
warnings, skip delta-spec sync, retain validation and the negative outcome.
No manual move or validation bypass. A future approach needs separately
authorized exploration and a distinct change/protocol; none is created here.
