# Spec Delta

## ADDED Requirements

### Requirement: Evidence feasibility and retrieval loss diagnostics
Диагностика SHALL отдельно показывать наличие всех обязательных evidence в inventory, точный minimum chunks полного покрытия с witness IDs/ranges либо невозможность покрытия, покрытие branch union и покрытие final top 5. При незавершённом вычислении minimum SHALL показываться unknown и проверенные bounds вместо заявления точного oracle. Она SHALL учитывать только original source ranges согласованного reference/namespace. Структурный oracle, branch recall, page hit, generated text и partial coverage SHALL NOT заменять Hit@5. Диагностика exposed holdout SHALL выполняться только в финальном отчёте после lock и SHALL NOT использоваться для выбора решения.

#### Scenario: Evidence needs six chunks
- **WHEN** в исходном q03 inventory каждая из шести частей необходима и никакие пять chunks не покрывают все spans
- **THEN** отчёт показывает minimum=6 и невозможность q03 Hit@5 на этом inventory, независимо от final k=6

#### Scenario: Candidate loss versus ranking loss
- **WHEN** полный inventory допускает cover в пяти chunks, но branch union не покрывает его либо top 5 теряет покрытие имеющего его union
- **THEN** отчёт различает candidate loss и final-ranking loss с IDs/ranges, не меняя evidence

### Requirement: Preregistered bounded quality experiments
До экспериментов SHALL фиксироваться fingerprints development protocol, допустимые данные, конечный набор policies/settings, selection rule, regression/resource gates и stop conditions. Experiment protocol SHALL быть первым обязательным gate каждой development фазы; отсутствие independent evaluator/package SHALL NOT блокировать development после его фиксации, но SHALL блокировать independent acceptance. Выбор SHALL использовать только разрешённый tuning; исторический exposed holdout и закрытый validation SHALL NOT влиять на выбор policies, параметров, rules или следующего кандидата. Потеря отдельных legacy tuning hits SHALL фиксироваться по IDs и SHALL NOT исключать кандидата; при равном итоговом числе tuning single-question hits предпочтение SHALL отдаваться варианту без таких потерь, до остальных tie-breaks. Обязательные integrity/resource и функциональные regression checks SHALL оставаться исключающими gates, отличными от case-level hit→miss transitions. Reports SHALL раскрывать все объявленные arms, ablations и причины исключения. RRF formula/control behavior, existing API defaults, question-only input и pure semantic contract SHALL сохраняться; альтернативный final ranking SHALL допускаться только в explicit opt-in mode нового protocol v2. Выбранный variant SHALL использовать отдельные settings/reports без изменения legacy snapshots.

#### Scenario: Development without independent package
- **WHEN** experiment protocol зафиксирован, но independent evaluator или закрытое package ещё отсутствуют
- **THEN** development tasks 2–5 могут выполняться, а independent acceptance остаётся незавершённой

#### Scenario: Historical holdout reveals a failure
- **WHEN** после lock финальный frozen report показывает новый или прежний holdout miss
- **THEN** текущая конфигурация сохраняется, miss публикуется и не запускается следующий tuning cycle на основании этого результата

#### Scenario: Minimal candidate selection
- **WHEN** несколько разрешённых кандидатов дают одинаковое качество на tuning
- **THEN** предпочтение получает вариант без потери legacy tuning hits; если этот критерий не различает кандидатов, применяются следующие зафиксированные tie-breaks, включая follow-up и меньшую сложность, без обращения к holdout

#### Scenario: More hits with a case-level regression
- **WHEN** кандидат проходит обязательные checks и даёт больше итоговых tuning single-question hits, но теряет отдельный legacy tuning hit
- **THEN** потеря фиксируется по case ID, кандидат не исключается и приоритет большего итогового числа hits сохраняется

### Requirement: Versioned continuation after negative development result
После v1 stop condition 5.2 система SHALL сохранять immutable protocol v1/receipt, все 36 reports/ablations, protected frozen inputs/baselines/snapshots и отрицательный результат best=6/9. Продолжение SHALL требовать отдельный experiment protocol v2 и receipt с hash протокола, code/worktree и protected inputs до implementation, model/tokenizer/runtime hashes до inference. V2 SHALL разрешать только один заранее зафиксированный cross-encoder candidate и два RRF controls на tuning, без повторного grid/model/limits/policy search. V2 SHALL NOT изменять evidence scorer protocol v1, budgets E5/chunking, expectations или denominator. Historical holdout SHALL NOT читаться или запускаться в development; final report SHALL оставаться единственным разрешённым использованием после lock.

#### Scenario: Old stop remains an immutable result
- **WHEN** начинается разрешённое review продолжение по experiment protocol v2
- **THEN** v1 result и 36 комбинаций остаются неизменными, отдельный v2 receipt проверяется до продолжения, новый кандидат не объявляется победителем v1 grid

#### Scenario: Missing commitment or another model
- **WHEN** отсутствует обязательный receipt/hash либо предлагается другой model artifact, precision, input policy или candidate limit
- **THEN** эксперимент не запускается без нового reviewed versioned protocol; fallback и скрытый перебор не допускаются

### Requirement: Bounded local cross-encoder ranking
Explicit experimental reranking SHALL использовать единственный CPU FP32 model artifact `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1@1427fd652930e4ba29e8149678df786c240d8825`, закреплённый protocol v2, с проверенными local safetensors/config/tokenizer, без remote code/network/training/quantization. Candidate union SHALL формироваться на прежнем read-only legacy inventory/literal v1 с S=120/L=1 (≤121 distinct chunks), без RRF top-k preselection, дополнительного recall/boost/page quota. Полная пара supplied question + неизменный stored search text SHALL проверяться собственным pinned tokenizer: question ≤128 tokens без special tokens, pair ≤512 включая четыре special tokens. При batch=1 SHALL использоваться padding=False и truncation=False: полная пара фактической длины ≤512 без padding до 512. Текст SHALL NOT обрезаться, заменяться windows/summaries или исключаться из union при overflow; любой preflight overflow SHALL останавливать experiment целиком. Scoring SHALL возвращать finite raw logit, порядок SHALL быть score descending/exact tie chunk ID ascending, final k=6 при неизменном scorer Hit@5. Output SHALL отдельно маркировать reranker/model/policy identity и score, сохраняя branch/RRF scores и original provenance; score SHALL NOT считаться answer confidence. Ошибка assets/inference SHALL завершаться явно без RRF/network fallback. Все прежние defaults/RRF/pure semantic/HTTP behavior SHALL сохраняться без opt-in.

#### Scenario: Evidence already in legacy union
- **WHEN** S120/L1 legacy union покрывает tuning q02 тремя chunks и q07 одним, но RRF final top-5 их теряет
- **THEN** reranker получает весь этот union до truncation final list, без L20/literal v2/rebuild; hit q02 требует все три evidence chunks среди первых пяти

#### Scenario: One irrelevant passage overflows
- **WHEN** любой кандидат полного union не помещается вместе с вопросом в pair budget либо question превышает 128 tokens
- **THEN** preflight останавливает весь эксперимент без inference quality report, dropping кандидата, truncation, windows или расширения бюджета

#### Scenario: Explicit mode preserves legacy controls
- **WHEN** выполняется прежний RRF или semantic search без opt-in reranker
- **THEN** прежние formula/ranks/scores/output/defaults/errors воспроизводятся без загрузки cross-encoder и изменения snapshots

#### Scenario: Failed local model does not silently change ranking policy
- **WHEN** выбран explicit reranker, но assets несовместимы, повреждены, отсутствуют либо получен nonfinite score
- **THEN** request/experiment завершается контролируемой ошибкой без выдачи fallback ranking и без сетевого доступа

### Requirement: Single candidate development decision and stop
V2 SHALL сравнивать legacy RRF 10/1/60/6, RRF control 120/1/60/6 и sole reranker на одинаковом legacy snapshot. Два последовательных fresh повтора с first/warm passes SHALL сохранять identical same-environment union/input hashes, finite scores/ranks/counts; все индивидуальные hit→miss против обоих controls, partial/rank losses и отдельные follow-up transitions SHALL регистрироваться. До lock SHALL проходить tuning-only resource screening под target i5-14400 Linux/Docker 4 CPU/5 GiB с совместно resident E5+reranker, no errors/OOM/cap violation и end-to-end single-question warm mean ≤2× legacy arm 1 в каждом повторе. Missing resource evidence SHALL NOT считаться pass. Whole-worker/container memory peak, swap/disk/init/first/warm и rerank durations SHALL измеряться отдельно. Development SHALL останавливаться при Hit@5 <8/9, mandatory input/integrity/resource/reproducibility failure либо незавершённых gates, оставляя lock/final/independent открытыми. Legacy q03 SHALL оставаться miss minimum=6 в denominator 9; case-level regressions SHALL быть отчётом, не отдельным exclusion gate. Успех development SHALL NOT заменять frozen/server/independent acceptance или разрешать tuning по holdout.

#### Scenario: Seven tuning hits or a slow candidate
- **WHEN** sole candidate даёт 7/9 либо ≥8/9 с warm mean >2× legacy или нарушением любого mandatory gate
- **THEN** сохраняется отдельный negative report и выполнение останавливается до lock/final/independent без нового model/limits/policy candidate

#### Scenario: Eight hits with legacy structural miss
- **WHEN** sole candidate проходит все development gates и даёт 8/9 с единственным q03 miss
- **THEN** допускается только lock, после которого нужны frozen ≥11/12, target-server acceptance и independent ≥90% в прежнем порядке; quality acceptance пока не достигнута

#### Scenario: Repeated scores differ
- **WHEN** одинаковые inputs/settings/runtime дают разные serialized finite logits, ranks или counts при fresh repeats
- **THEN** reproducibility gate не пройден, settings не донастраиваются и experiment останавливается для review

### Requirement: Improvement stage quality acceptance
Приёмка этого этапа SHALL требовать live single-question evidence Hit@5 ≥90% на неизменном frozen v1 (минимум 11/12), успешной отдельной независимой validation ≥90%, integrity/regression checks и повторяемой фактической серверной проверки. Финальные проверки SHALL выполняться в порядке lock → frozen v1 → target-server acceptance → independent validation; каждый следующий шаг SHALL требовать успеха обязательных предшествующих gates. При провале или незавершённости любого такого gate закрытый validation package SHALL оставаться невскрытым и не запускаться. Frozen report SHALL сохранять protocol v1 и denominator 12=9 tuning+3 exposed holdout, отдельно показывать splits, follow-up, synthetic и refuse/clarify. Independent validation SHALL NOT добавляться в frozen denominator. Counts/ranks/scores SHALL воспроизводиться при одинаковых inputs/environment; latency/memory SHALL измеряться отдельно. Resources SHALL соответствовать preregistered CPU/RAM/latency/Wiki.js gates. Historical baselines/reference/expectations SHALL оставаться неизменными. Техническая реализация SHALL NOT закрывать quality acceptance при недостигнутом пороге либо отсутствии независимой/серверной проверки.

#### Scenario: Mandatory gate fails before independent validation
- **WHEN** locked решение не проходит frozen v1 threshold либо обязательные target-server integrity/regression/resource/reproducibility checks
- **THEN** последующие acceptance шаги не выполняются, причина публикуется, закрытый validation package не вскрывается и не запускается, quality acceptance остаётся открытым

#### Scenario: Threshold arithmetic
- **WHEN** frozen v1 даёт 10/12 либо 11/12 полных hits
- **THEN** frozen threshold соответственно не достигнут либо достигнут; успех synthetic/follow-up не меняет этот статус

#### Scenario: Independent check is absent or fails
- **WHEN** frozen v1 даёт ≥11/12, но независимая проверка отсутствует или даёт <90%
- **THEN** отчёт различает достигнутый frozen target и незавершённую independent acceptance, а quality task остаётся открытой

#### Scenario: Server reproducibility and resource evidence
- **WHEN** выбранный variant проходит два offline запуска на целевом Linux/Docker сервере
- **THEN** отчёт содержит matching artifact/environment identities, одинаковые ranks/scores/counts, отдельные model loading/init/first-query/warm latency, whole-worker peak RSS/container memory peak, model bundle disk increment/swap/available memory измерения и Wiki.js baseline/load samples с проверкой заранее заданных gates; в experiment v2 chunking/embedding/FTS rebuild не выполняется, соответствующие build durations, build-only RSS и build disk increments отмечаются N/A с причиной reuse read-only snapshot, а исторические build records v1 сохраняются отдельно

## MODIFIED Requirements

### Requirement: Deterministic reciprocal rank fusion
В default RRF mode система SHALL объединять semantic и lexical candidate lists через RRF: score(chunk) = сумма `1 / (rrf_constant + branch_rank)` по веткам, где присутствует chunk, с rank начиная с 1. Defaults SHALL быть semantic candidates=10, lexical candidates=10, rrf_constant=60 и final top-k=6. Raw cosine и BM25 SHALL NOT складываться или нормализоваться друг к другу; literal priority SHALL влиять на lexical rank до RRF без отдельного post-fusion boost. Каждый chunk SHALL встречаться в final list один раз по chunk ID в пределах одного snapshot, сохраняя разные chunks одной страницы. В RRF mode final order SHALL быть RRF score по убыванию, при равенстве chunk ID по возрастанию; final rank SHALL начинаться с 1. Top-k выше union size SHALL возвращать весь union без добора из кандидатов за пределами branch limits. Единственное дополнительное final-ranking поведение SHALL допускаться через explicit opt-in bounded local cross-encoder mode по experiment protocol v2: полный тот же union ранжируется finite logit descending/exact tie chunk ID ascending до final cutoff; RRF score SHALL сохраняться отдельно и SHALL NOT смешиваться с logit. Без opt-in прежний RRF contract SHALL воспроизводиться полностью.

#### Scenario: Known branch rankings and overlap
- **WHEN** в RRF mode chunk имеет semantic rank 2 и lexical rank 3 при константе 60
- **THEN** его score равен `1/62 + 1/63`, chunk возвращается один раз и сохраняет оба branch ranks

#### Scenario: Ties and single-branch candidates
- **WHEN** в RRF mode union содержит одинаковые RRF scores, chunk только одной ветки и несколько chunks одной страницы
- **THEN** ties разрешаются по chunk ID, missing branch не даёт contribution, отдельные chunks страницы сохраняются

#### Scenario: Final limit and literal priority
- **WHEN** в RRF mode exact literal поднят на первое место lexical list, а final k превышает число уникальных branch candidates
- **THEN** RRF использует новый lexical rank и возвращает только union, без глобального exact-match override и дополнительного добора

#### Scenario: Explicit cross-encoder does not redefine RRF
- **WHEN** явно выбран bounded reranker mode с отдельными settings/model identity
- **THEN** final order определяется его logit без предварительного RRF top-k cutoff, а прежние branch ranks/scores/RRF score сохраняются отдельно и default RRF mode остаётся воспроизводимым
