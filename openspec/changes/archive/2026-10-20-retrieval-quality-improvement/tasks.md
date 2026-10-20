# Tasks

Все пункты относятся к будущему apply. Этот propose не выполняет implementation tasks. Порог качества не заменяется технической готовностью.

Planning revision 2026-10-16: выполненные development tasks 1.1, 2–4, 5.1–5.2 и отрицательный результат 36 комбинаций сохранены; 1.2–1.3 остаются открытыми. Новое продолжение — только tasks 5.4–5.8 по experiment protocol v2; reranker не реализован, модель не скачана, новые эксперименты не запускались. Зависимости продолжения: 5.4 → 5.5 → 5.6 → 5.7 → 5.8 → 5.3 → 6.1 → 6.2 → 6.3. V1 и evidence scorer protocol v1 не заменяются experiment protocol v2.

Первый обязательный gate — task 1.1 (experiment protocol). После него development tasks 2–5 могут выполняться без завершения tasks 1.2–1.3: evaluator/package готовятся параллельно, их отсутствие блокирует independent acceptance, но не development. Финальная последовательность: lock (5.3) → frozen v1 (6.1) → target-server acceptance (6.2) → independent validation (6.3). При провале или незавершённости обязательного предшествующего gate закрытый package не вскрывается и не запускается.

## 1. Development protocol и независимая выборка

- [x] 1.1 Зафиксировать отдельный experiment protocol до изменений и экспериментов: allowed data, 36 комбинаций из design, selection/tie-break, исключающие integrity/resource/функциональные regression gates, учёт case-level hit→miss как отчёта и tie-break, lock и stop conditions; проверить hash протокола, порядок финальных gates и неизменность frozen questions/manifest/reference/baselines/snapshots относительно сохранённой передачи. Этот пункт обязателен перед tasks 2–5.
- [ ] 1.2 Параллельно development согласовать независимого evaluator и подготовить закрытое package с ≥20 новыми answerable live single-question holdout cases и отдельными follow-up/answerless cases по design; проверить semantic review, отсутствие парафразов старого corpus/отбора по miss IDs, обязательное coverage существующего validator и заранее зафиксированные fingerprints. При отсутствии evaluator/package оставить пункт и independent acceptance открытыми, продолжая tasks 2–5 после task 1.1.
- [ ] 1.3 Документировать запуск отдельного package через existing validator и `--split holdout`, не включая служебный tuning в independent denominator; evaluator выполняет offline integrity validation до independent retrieval без передачи закрытых questions/expectations разработчику и сохраняет отдельный validation receipt. Этот пункт требуется для task 6.3, но не блокирует tasks 2–5.

## 2. Диагностика достижимости и потерь

- [x] 2.1 Расширить evaluation/comparison диагностикой inventory coverage, minimum source-range cover с witness/bounds, branch-union coverage и final top-5 loss без изменения `evidence_hit` semantics; целевые tests проверяют missing evidence, minimum=6, overlap, generated-only ranges, namespace mismatch и unknown при незавершённом minimum.
- [x] 2.2 Воспроизвести на разрешённом tuning исходные q02/q03/q07 причины и q03 minimum=6, сохранив IDs/ranges/fingerprints и отдельный development report; проверить полное совпадение исходных tuning hits/ranks с legacy baseline без запуска holdout кандидатов.
- [x] 2.3 Документировать диагностику и арифметику 11/12 в отдельном quality workflow document, включая различие структурной верхней границы и Hit@5; проверить примеры cover≤5/ranking miss и default k=6/scorer k=5 целевыми evaluation/comparison tests.

## 3. Versioned упаковка prose/code

- [x] 3.1 Добавить явный legacy/new policy selection в chunking и упаковку соседнего pending prose/короткого code одного heading path по design; целевые chunking structure/CLI tests проверяют целый блок, body/input budgets, CRLF/Unicode ranges, section/page boundaries, preservation tables/long continuations и побайтовое воспроизведение legacy output.
- [x] 3.2 Проверить на реальных локальных E5 assets q03 tuning пару `[6504,6579)` + `[6579,6595)` и minimum≤5 нового inventory; сохранить отдельный feasibility report с witness и token maxima. Если общее правило не помогает, зафиксировать провал и остановить эту ветку до review без специального join или изменения budgets.
- [x] 3.3 Пройти новую algorithm identity через storage/semantic/lexical readers, меняя только необходимые supported-version checks; целевые storage/semantic tests проверяют приём обеих известных algorithm versions, отказ unknown/corrupt versions, прежнюю base schema и no stale vectors.
- [x] 3.4 Построить отдельный новый chunks/storage/E5/lexical snapshot, измерить rebuild/disk стоимость и проверить docs/ranges/tokenizer/model identity, полный новый vector inventory, repeat hashes и сохранность inputs при failure; документировать команды build/rollback в quality workflow document и выполнить их offline.

## 4. Underscore literal policy

- [x] 4.1 Добавить v2 extraction полных underscore identifiers, сохранив quoted/IP/path/hyphen и source-backed boundaries; целевые lexical tests проверяют два явных поля, похожие suffix identifiers, quoted command целиком, generated/discontinuous false matches и прежние v1 результаты.
- [x] 4.2 Добавить explicit build selection, metadata validation/dispatch v1/v2 и report identity; lexical storage/CLI и hybrid tests проверяют legacy reproduction, unknown-policy error и byte equality base/provenance/embeddings при literal-only rebuild отдельного snapshot.
- [x] 4.3 Документировать v1/v2 build/query/rollback и выполнить offline CLI smoke для обеих policies; проверить lexical-only запуск без model assets/heavy embedding imports и сохранность исходного snapshot.

## 5. Ограниченные tuning эксперименты и lock

- [x] 5.1 Выполнить объявленную сетку только на tuning, сохранив все результаты/ablations, per-case transitions, witness/branch/final coverage, cold/warm latency и peak memory; comparison tests проверяют split isolation, соответствие policy/settings fingerprints, unchanged denominator и отсутствие автоматической загрузки holdout для выбора.
- [x] 5.2 Выбрать минимальный допустимый вариант по зафиксированному selection rule и обязательным integrity/resource/функциональным regression gates; проверить воспроизводимость выбора, отчёт потерянных legacy tuning hits по IDs и арифметическую достижимость ≥11/12. Проверить, что такие потери не исключают кандидата, а при равном итоговом числе tuning single-question hits предпочтение получает вариант без потерь до остальных tie-breaks. При лучшем tuning <8/9 сохранить отрицательный результат и остановиться до независимого validation, оставив quality task открытой.
- [ ] 5.3 Только после успеха 5.8 зафиксировать code revision/worktree fingerprint, legacy snapshot, E5 и cross-encoder model/tokenizer/policy fingerprints, hash experiment protocol v2 и отдельный opt-in settings file до финальных проверок; проверить совпадение repeated tuning ranks/scores/counts и прежние RRF/API defaults/pure semantic/HTTP health целевыми regression tests, обновить quality workflow document с точными командами. Не считать v1 selected development variant acceptance lock.

### Продолжение после review stop condition: один experiment v2

- [x] 5.4 До implementation продолжения создать отдельный `docs/retrieval-quality-protocol-receipt-v2.json`: hash `docs/retrieval-quality-experiment-protocol-v2.md`, дата, code/worktree identity, legacy snapshot/protected input hashes из v1 handoff, hashes immutable v1 protocol/receipt/result/grid и всех 36 reports. Проверить сохранность прежних artifacts, неизменные denominator/scorer и отсутствие development holdout; подтвердить единственные S120/L1/literal1/legacy и model revision из protocol v2. Missing/mismatching commitment блокирует следующие tasks.
- [x] 5.5 В отдельном будущем apply подготовить offline bundle только заранее выбранного `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1@1427fd652930e4ba29e8149678df786c240d8825`, FP32 safetensors и fast tokenizer/config той же revision. До inference проверить published weights/tokenizer SHA-256, полный file manifest, Apache-2.0/model-card provenance, existing pinned runtime и local-only/no-remote-code загрузку без сети; добавить bundle/runtime identities в отдельный v2 receipt. При missing/incompatible/corrupt asset остановиться без fallback/другой модели; никаких новых dependencies/export/quantization. Скачивание не входит в текущую planning revision.
- [x] 5.6 Реализовать только opt-in CPU reranking полного legacy S120/L1 union (≤121), без изменения RRF/defaults/pure semantic/HTTP health и без rebuild. Целевые tests проверяют dedup по chunk ID, сохранение нескольких chunks страницы, отсутствие pre-RRF cutoff, question + полный search_text, реальные tokenizer pair budgets ≤512/question≤128 при batch=1, padding=False и truncation=False (полная пара фактической длины без padding до 512), детерминированный finite raw logit/tie order, model errors/no fallback и отдельные output score identities/provenance. Документировать app/Compose query/evaluate/rollback. До quality inference выполнить общий token preflight всех разрешённых tuning pairs (follow-up отдельно); overflow любого candidate останавливает весь experiment, без dropping/windows/смены budgets. Structural tests не доказывают live quality.
- [ ] 5.7 После 5.4–5.6 выполнить ровно три tuning arms: legacy RRF 10/1/60/6, RRF control 120/1/60/6 и единственный reranker на том же полном union. Два fresh sequential повтора каждого arm с first/warm passes; сохранить все union IDs/input hashes/token maxima/finite scores/ranks/counts, q02 full-three/q07 one-chunk coverage и все индивидуальные legacy/control hit→miss, partial/rank/follow-up transitions. Провести tuning-only resource screening под target 4 CPU/5 GiB, E5+reranker resident вместе: целиком end-to-end warm mean ≤2× legacy arm 1 в обоих повторах, no errors/OOM/cap violation, whole-worker/container peak memory, swap, model bundle disk increment, model loading/init/first/warm/rerank timings. Chunking/embedding/FTS rebuild не выполнять; build durations, build-only RSS и build disk increments отметить N/A (read-only snapshot), сохранив исторические build records v1 отдельно. Проверить protected hashes, exact same-environment repeat ranks/scores/counts и split isolation; reports/measurements только в новых v2 paths. Это development screening, не task 6.2 и не разрешение читать historical holdout.
- [x] 5.8 Выпустить отдельный v2 decision report без изменения v1 negative result: допускается только sole candidate с ≥8/9 полных tuning single-question hits и всеми mandatory input/integrity/reproducibility/resource gates. q03 minimum=6 остаётся denominator miss; все остальные восемь cases должны стать hits. Индивидуальные регрессии фиксировать против обоих controls даже при росте totals, без отдельного case-level exclusion gate. При <8/9, любом mandatory failure или неполных gate evidence сохранить отрицательный/incomplete report и stop до 5.3/6, не запускать другой model/limits/policy/tuning cycle и не расходовать validation. При успехе разрешить лишь 5.3 lock; подтвердить прежний порядок frozen ≥11/12 → server → independent ≥90% и отсутствие claim о пройденной quality acceptance.

## 6. Финальная оценка и серверная приёмка

- [ ] 6.1 После lock (5.3) выполнить один финальный frozen comparison: сохранить semantic/lexical/RRF modes и добавить отдельно именованный locked reranker arm, с отдельными tuning/exposed-holdout/follow-up/synthetic/answerless результатами и per-case loss diagnostics; проверить evidence scorer protocol v1, experiment protocol v2 identity, неизменные protected hashes, числитель/знаменатель 12, статус ≥11/12 именно locked решения и отсутствие обратного tuning по misses. При провале threshold или обязательных checks оставить gate открытым и не выполнять tasks 6.2–6.3, сохранив закрытый package.
- [ ] 6.2 Только после успеха frozen v1 gate (6.1) выполнить два фактических offline Linux/Docker server запуска locked artifacts под 4 CPU/5 GiB, последовательно с legacy comparison; сохранить environment/artifact identity, repeat ranks/scores/counts, model loading/init/first/warm, whole-worker RSS/container memory peak, model bundle disk increment/swap/available memory и Wiki.js ≥20 baseline/≥20 load samples. V2 не выполняет chunking/embedding/FTS rebuild: build durations, build-only RSS и build disk increments отметить N/A с причиной reuse read-only snapshot, не нулём; исторические build records v1 сохранить отдельно. Проверить integrity, функциональные regression checks, threshold ≥11/12, воспроизводимость, отсутствие ошибок/OOM, warm mean ≤2× legacy и Wiki.js p95 ≤2× baseline по preregistered методике. При провале любого обязательного условия оставить server gate открытым и не выполнять task 6.3, сохранив package невскрытым и неиспользованным.
- [ ] 6.3 Только после успеха frozen v1 (6.1), target-server acceptance (6.2) и готовности evaluator/package (1.2–1.3) независимому evaluator вскрыть и выполнить закрытый validation locked решения с тем же scorer, повтор допустим только идентичный; сохранить separate report с live numerator/denominator, misses, Wilson interval и disclosure. Проверить ≥90% отдельно, не смешивая с frozen 12; failed/absent validation оставляет independent acceptance открытой. При отсутствии любого prerequisite не вскрывать и не запускать package.
- [ ] 6.4 Подтвердить quality acceptance только при frozen ≥11/12, independent ≥90%, пройденных integrity/regression/resource checks и серверной воспроизводимости; опубликовать отдельный итоговый report со статусами и limitations. При любом недостигнутом условии оставить этот пункт открытым, перечислить misses/причину и не заявлять завершённый retrieval критерий MVP.

## Implementation status, 2026-10-16

- 1.2–1.3: владелец отложил назначение независимого evaluator. Закрытый reviewed package, fingerprints и evaluator offline validation receipt не предоставлены. Процедура документирована, фактическая независимая проверка не выполнена.
- 5.2 stop condition: все 36 tuning комбинаций проверены; лучший допустимый результат 6/9 <8/9, даже при идеальном holdout максимум 9/12 <11/12. Отрицательный результат: `docs/retrieval-quality-result.md`; полная сетка: `docs/retrieval-quality-tuning-grid.json`.
- 5.3 и 6.1–6.4 оставлены открытыми: development stop запрещает переход к lock/final acceptance до review расширения плана. Frozen candidate comparison, target-server acceptance и independent retrieval не запускались. Закрытый package не вскрывался; quality acceptance не достигнута; change не архивирован.

## Planning continuation status, 2026-10-16

Review расширил planning scope ровно одним CPU cross-encoder experiment по protocol v2 (5.4–5.8). Историческая остановка 5.2 остаётся фактом и не снимается задним числом. Новые tasks не выполнены; 5.3 и 6.1–6.4 остаются открытыми до успеха нового development gate. Назначение evaluator/package по-прежнему отложено и independent acceptance не выполнена. Текущая revision меняет только planning artifacts/protocol; no implementation/download/inference.












## Apply status, 2026-10-19

- 5.4 completed: separate v2 protocol receipt commits protocol/code/worktree identity, all 9 protected input hashes, immutable v1 artifacts and 36 report hashes. Eight v1 implementation hashes match the verification receipt; all 36 reports retain scorer protocol v1, tuning-only cases and denominator 9.
- 5.5 blocked: pinned cross-encoder bundle is absent. Installed package metadata matches the three pinned runtime versions, but offline model/tokenizer verification is not complete. Download approval was rejected by the user; no bundle download, model loading, inference or fallback was performed.
- 5.5 remains unchecked; 5.6 onward were not started. Historical holdout and closed validation were not read or executed. Lock and quality acceptance remain open. Resume requires the exact pinned local bundle and completion of 5.5.

## Apply continuation, 2026-10-19

- 5.4 was not repeated; its commitment and worktree identity remain unchanged.
- 5.5 completed: user-authorized download of the exact pinned revision; six-file manifest and published weights/tokenizer SHA-256 verified, pinned runtime and guarded offline CPU/FP32/fast-tokenizer loading passed with zero network attempts. Assets remain under ignored data/models; bundle/runtime evidence extends the existing v2 receipt.
- 5.6 completed: explicit app.reranking CLI, full legacy S120/L1 union scoring, source/branch/RRF/reranker identities, no padding/truncation/fallback; documented application/Compose-image query/evaluate/rollback. Global live-answerable preflight: 1,201 pairs, max question 25 and max pair 469; all-tuning CLI preflight: 14 cases, 1,682 pairs, max 469, no overflow. Targeted tests and typing passed; no cross-encoder live quality inference performed.
- 5.7 pending: target Linux/Docker 4 CPU/5 GiB execution is unavailable from the current Windows environment (Docker missing); server connection details requested. Operator-provided free disk/RAM/swap observations do not replace actual screening measurements. Three arms/two fresh repeats have not run.
- 5.8 and lock/final/independent acceptance remain open. Incomplete v2 status report: docs/retrieval-quality-result-v2.md. No holdout/closed validation use or substitute quality/resource claim.


## Evidence review and negative decision, 2026-10-20

This status supersedes earlier pending-server status; entries above describe
their respective dates. Archive rq57-20261019-01-results.tar SHA-256
`e98c230fbec36f0071e36649cb76b8390844d006358942e1b4bb112c81cd1d7b`
verified; 60 files safely extracted separately. Actual execution: 2026-10-20.
See `docs/retrieval-quality-result-v2.md` and `docs/retrieval-quality-evidence-audit-v2.json`.

- 5.8 completed as the protocol-required negative/incomplete decision report:
  legacy/control/reranker 6/9, 6/9, 4/9; warm means 0.009478/0.009546/2.446002 s;
  ratio 258.071122x. Quality >=8/9 and latency <=2x both fail. STOP applies;
  completing the negative report does not authorize its success branch.
- 5.7 remains `[ ]`: only repeat 1 of all three arms exists, with matching
  first/warm passes. Two fresh runs and across-worker reproducibility are not
  established. First-run failure is sufficient for rejection, not full task
  completion. Runbook blocks repeat 2 after failure; no repeat was run.
- 5.4-5.6 remain completed. Audit verified 141 transport files before reporting
  edits, 76 commitments, seven server integrity receipts, inputs, unions,
  finite scores, provenance and all 84 saved row hits/cover diagnostics.
  Docker exit=0/no OOM, 4 CPU/5 GiB and zero container swap are evidenced for
  first runs; these are not final server acceptance.
- 5.3 blocked: failed development quality/resource gates prohibit lock.
- 6.1 blocked: no admissible locked candidate; frozen >=11/12 untested.
- 6.2 blocked: no successful 6.1; screening is not final server acceptance.
  Two accepted repeats and Wiki.js baseline/load evidence are absent.
- 6.3 blocked: 6.1/6.2 prerequisites unmet; evaluator/package/validation receipt
  from 1.2-1.3 absent. Closed validation remains unused.
- 6.4 blocked: frozen/server/independent acceptance unmet; publishing a negative
  report does not close quality acceptance.
- 1.2-1.3 remain `[ ]`: evaluator appointment/reviewed closed package/commitments
  and actual evaluator offline validation receipt are not supplied.

Only 5.8 newly checked: **17/25 complete, eight open**. No inference, historical
holdout, independent validation or next experiment launched in this review.
Model/policy/thresholds/protocol v2 remain unchanged. Requested result.md addendum
is a post-experiment reporting change: original v1 bytes are preserved at
`docs/retrieval-quality-result-v1-frozen.md` with original committed hash.
Receipts still refer to the pre-addendum state and are not rewritten.
Owner decision, 2026-10-20: **experiment v2 ended negatively; cross-encoder
reranker rejected**. The eight unfinished tasks retain their reasons above;
they will not be executed to complete this rejected branch. No checkbox changes.
Proposed next administrative step, only on later archive authorization: standard
archive with acknowledgment of eight incomplete tasks, Archive without syncing,
validation enabled and the negative outcome retained. Do not remove tasks,
fabricate completion, sync experimental deltas or manually move the directory
to evade warnings. See the v2 report for the full closure plan and task map.
New retrieval design requires separate authorization and a distinct future
change/protocol; nothing new is created or executed now.
Change remains unarchived; retrieval quality MVP acceptance is open.
