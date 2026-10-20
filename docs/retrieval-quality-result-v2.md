# Retrieval quality v2: negative development decision

2026-10-20. **STOP: quality and latency gates failed. No acceptance lock.**
Task 5.8 is complete as a negative decision, not candidate acceptance.
Task 5.7 remains incomplete: only one fresh run of each arm exists.
Owner decision, 2026-10-20: **experiment v2 ended negatively; cross-encoder
reranker rejected**. This branch will not resume. Protocol v2 is unchanged;
no further runs are authorized. Administrative archive completed on 2026-10-20
at `openspec/changes/archive/2026-10-20-retrieval-quality-improvement/`, without
spec synchronization, retaining 17/25 completed tasks and eight unfinished tasks.
No further inference, historical holdout, independent validation or experiment
was performed during this evidence review.

## Evidence and scope

Archive: `data/retrieval-quality-improvement/reranker-v2/download-20261019-01/rq57-20261019-01-results.tar`.
SHA-256: `e98c230fbec36f0071e36649cb76b8390844d006358942e1b4bb112c81cd1d7b`.
The digest matches. All 60 regular files were extracted into the new
`download-20261019-01/verified-extracted/` directory, preserving the embedded
`data/retrieval-quality-improvement/reranker-v2/manual-20261019-01/` layout.
No duplicate paths, links or traversal; all extracted bytes match TAR members.
The original archive remains intact. Raw filenames below refer to that run.

The [audit receipt](retrieval-quality-evidence-audit-v2.json) records all 60
file hashes, pre-documentation local comparisons, measurements, transitions,
missing spans and witness ranks. The audit script is retained at
`data/retrieval-quality-improvement/reranker-v2/download-20261019-01/audit_saved_evidence.py`.
Its pre-documentation comparisons describe the state before the reporting edits,
not a new execution commitment. It audits saved data without retrieval/model loading.

Despite the run ID, Docker timestamps place execution on **2026-10-20,
08:33-08:35 Europe/Moscow**. Environment: Linux x86-64, Intel Core i5-14400,
Python 3.12.15, torch 2.7.1+cpu, transformers 4.57.3, tokenizers 0.22.2.
All arms use image `sha256:feef02b2beaa8c5b5eb7b34bc3c88052b9134451769d49b48e30bea4c50fdd49`.
Image build succeeded; `pip-check.txt` reports no broken requirements.
This is tuning screening, not task 6.2 target-server acceptance.

## Quality and latency

Metrics were recalculated from saved rows. Each arm contains 14 tuning cases x
first/warm passes. Only nine live answerable single questions form the quality
denominator; one follow-up and four answerless/synthetic cases remain separate.
Scorer remains protocol v1, full source-range coverage in top-5, final k=6.

| Arm | S/L/RRF/k | Hits | Warm arithmetic mean, seconds |
| --- | --- | --- | --- |
| Legacy RRF | 10/1/60/6 | 6/9 | 0.009478016859955259 |
| RRF control | 120/1/60/6 | 6/9 | 0.00954579727517234 |
| Sole CPU reranker | full control union | 4/9 | 2.4460024444593325 |

Reranker/legacy ratio: **258.07112190248614x**, versus mandatory <=2x
(ceiling 0.018956033719910518 seconds). Quality: **4/9 <8/9**.
Both independently require STOP. First/warm serialized scores, ranks, counts,
unions, inputs, hits and diagnostics match exactly within each worker.
This does not establish fresh-repeat reproducibility: repeat 2 is absent.

| Case | Legacy | Control | Reranker | Saved evidence diagnosis |
| --- | --- | --- | --- | --- |
| q01 | hit | hit | miss | Evidence witness demoted to rank 20 |
| q02 | miss | miss | miss | Full three-chunk union cover; witnesses rank 1/20/28 |
| q03 | miss | miss | miss | Inventory minimum=6; union also misses a required range |
| q05 | hit | hit | hit | Retained |
| q06 | hit | hit | hit | Retained |
| q07 | miss | miss | hit | Full one-chunk evidence at rank 4 |
| q11 | hit | hit | hit | Retained |
| q12 | hit | hit | miss | Evidence witness demoted to rank 12 |
| q19 | hit | hit | miss | Inventory witness chunks rank 109/116 |

Against **both** controls: gain q07; hit-to-miss q01/q12/q19; net -2 hits.
Transitions are reported, not an extra case-level exclusion gate. q02 partially
improves but still misses page 3 spans [454,505) and [697,725) in top-5;
a rank-1 passage is insufficient. q03 remains in the denominator.
Separate follow-up q09 remains miss in all arms: reranking covers more evidence,
but page 17 [8048,8065) is still missing, with inventory witnesses rank 1/44.
Answerless/synthetic rows do not establish answer correctness. All transitions,
final lists and partial/rank diagnostics match `summary-1.json` and arm reports.

## Resources and Docker

| Measurement | Legacy | Control | Reranker |
| --- | --- | --- | --- |
| Whole-worker peak RSS, bytes | 1,138,499,584 | 1,140,441,088 | 1,777,270,784 |
| Container cgroup memory peak, bytes | 1,005,285,376 | 1,002,999,808 | 1,579,020,288 |
| E5 loading, seconds | 2.400462 | 2.405278 | 0.696210 |
| Index initialization, seconds | 0.635386 | 0.636043 | 0.633279 |
| First query, seconds | 2.411491 | 2.416859 | 3.753067 |

E5 and cross-encoder were resident together in the candidate worker.
Cross-encoder initialization: 3.080555 seconds; weights loading: 0.184199 seconds.
Reranker warm means: semantic 0.007931, lexical 0.002161, tokenization 0.111349,
rerank 2.403788 seconds. Tokenization is nested in reranking; these timers must
not be summed as disjoint costs. Reranking the full union dominates recorded
latency; the data do not isolate individual CPU operators or generalize to other models.

All three Docker states: exited, **exit 0**, `OOMKilled=false`, empty error/stderr.
Container/image IDs match before/after inspect. Docker and cgroups confirm
**4 CPU / 5 GiB**, container swap disabled, network none, read-only root/work
mount and separate writable output. Cgroup max/oom/oom_kill events are zero,
peaks below cap, container swap usage zero. Recorded CPU throttling is not a
cap violation. RSS and cgroup peak have different accounting and remain separate.

Host free/meminfo arm-boundary snapshots show 8.64-8.94 billion available bytes.
Host swap is already occupied by **4,179,169,280 bytes**, unchanged at all
boundaries; vmstat samples show si=so=0. This does not mean swap was empty or
prove no activity between samples. No observed OOM/cap failure explains rejection.

Verified bundle size: **487,679,201 bytes**, sum of artifact file sizes, not
allocated filesystem blocks or RSS. No chunking/embedding/FTS rebuild ran:
build duration, build-only RSS and build disk increment are **N/A: reuse read-only
snapshot**, not zero. Historical v1 build records remain separate.
`image-build.log` concerns the runtime image. No Wiki.js baseline/load samples
or after-service health verification are supplied; `services-before.txt` is
only an inventory. Final Wiki.js/server acceptance remains untested.

## Integrity and limitations

- All **141** transport file hashes matched local copies before reporting edits,
  including code, model assets, inputs and historical reports. All **76** committed
  identities were rechecked locally. Seven server receipts (initial, before/after
  each arm) report the same 76 commitments and transport manifest hash.
- Archived protocol and v2 receipt equal local committed copies. Protocol v2 hash
  remains `6efdb9a7cbd836145926483669e60735f76409222e8fe459d631dff1493e7a47`.
  Legacy snapshots, nine protected inputs, v1 protocol/receipt/grid and 36
  historical reports match commitments. No protocol or receipt was rewritten.
- Preflight: 14 tuning cases, **1,682 pairs**, question max **25/128**, pair max
  **469/512**. Reranker inputs equal preflight inputs; full deduplicated control
  unions and input hashes match in both passes, at most 121 chunks. All scores
  are finite with descending-logit/exact-chunk-ID tie order. Source provenance,
  input hashes, hits and complete cover diagnostics were checked against validated
  read-only snapshots for **all 84 saved rows**.
- All rows are tuning. Historical holdout was filtered out before evaluation;
  no holdout diagnostics/retrieval or closed validation were used in this review.
  Runtime reports record zero network attempts, with Docker networking disabled.
  The evidence does not indicate fallback, changed policy/model, truncated union
  or stale vectors. No cross-platform score equality is claimed.
- `manual-local-checks.txt` records historical **8 synthetic measurement tests
  and 75 application tests**, one existing deprecation warning. Its fabricated
  `repeat=2`, 8/9 outputs are **test fixtures, not actual server repeat 2**.
  Those tests were not rerun during this documentation-only review.
- The explicit request to append v2 to `retrieval-quality-result.md` changes that
  path's historical hash. Original v1 bytes are preserved in
  [retrieval-quality-result-v1-frozen.md](retrieval-quality-result-v1-frozen.md),
  SHA-256 `49008ac640564014fc4e2e5d4fabaaa766a472102ae671f35f11a9c607f58a42`.
  Existing receipts still commit the pre-addendum path and remain unchanged;
  they must not be presented as matching that path after this reporting edit.
  This disclosed post-experiment change is not an experiment integrity failure
  or a new executable commitment.

## Tasks and next decision

**Close 5.8:** the required separate negative/incomplete report and STOP decision
are recorded; its success branch is not taken. Tasks 5.4-5.6 remain completed
on existing commitment/bundle/implementation evidence.

**Keep 5.7 `[ ]`:** all three arms ran once with first/warm passes, but mandatory
second fresh runs and across-worker exact reproducibility are absent.
First-run failure is sufficient to reject, insufficient to claim full execution
of 5.7. The runbook blocks repeat 2 after a failed summary; do not fill this
checkbox by running it after STOP.

**Keep 5.3 `[ ]`:** failed development gates prohibit lock.
**Keep 6.1-6.4 `[ ]`:** no lock, successful frozen >=11/12, final server acceptance
or independent >=90%; negative reporting does not close quality acceptance.
**Keep 1.2-1.3 `[ ]`:** evaluator/reviewed closed package/commitments and actual
offline validation receipt remain absent. A documented procedure is insufficient.
Progress: **17/25**, eight tasks open.

The sole fixed candidate fails to preserve full evidence in top-5 and adds large
CPU ranking cost. This is failure on this tuning corpus/envelope, not evidence
that all rerankers fail. Even hypothetical perfect historical holdout would
yield at most 7/12 from tuning 4/9, below 11/12; no holdout execution is needed.

Owner review has ended this candidate branch. Keep model/policy/thresholds/
protocol v2 unchanged. For a separately authorized future approach, order remains
successful development -> lock -> frozen >=11/12 -> final server acceptance ->
independent >=90%. Closed validation remains unused; quality MVP acceptance
stays open. The change is archived as a negative experiment, not accepted retrieval.

## Proposed administrative completion after owner rejection

The plan below was approved and executed on 2026-10-20 using
`openspec.cmd archive retrieval-quality-improvement --skip-specs`, with the
standard eight-incomplete-task warning explicitly confirmed. It is retained
as the historical closure plan, not a request for another archive operation.
Post-archive checks: `openspec validate --all --strict` passed (9/9),
`git diff --check` passed; archived files and 17/25 task states are byte-identical
to the pre-archive snapshot. Raw evidence, protocol/receipts, SPEC.md, ROADMAP.md
and all main specs are unchanged. No inference or new change was performed.

Owner rejection ends execution, not the outstanding quality obligations.
Keep all 25 original tasks, with 17 checked and eight unchecked. Do not delete,
reclassify as completed or rewrite unfinished tasks to improve the count.
Checked implementation/test/report tasks do not imply candidate acceptance.

| Tasks | Factual disposition |
| --- | --- |
| 1.1 | Complete: original protocol commitment |
| 2.1-2.3 | Complete: diagnostics, reproduction and documentation |
| 3.1-3.4 | Complete: packing, feasibility, compatibility and rebuild audit |
| 4.1-4.3 | Complete: literal policy, compatibility and offline checks |
| 5.1-5.2 | Complete: v1 grid and negative selection decision |
| 5.4-5.6 | Complete: v2 commitment, verified bundle, implementation/preflight |
| 5.8 | Complete: negative report; success branch not taken |
| 1.2 | Incomplete: evaluator/reviewed closed package/commitments absent |
| 1.3 | Incomplete: actual evaluator offline validation receipt absent |
| 5.7 | Incomplete/stopped: first screening failed; second fresh runs absent and prohibited |
| 5.3 | Blocked/not executed: development gates failed; candidate rejected; no lock |
| 6.1 | Blocked/not executed: no admissible locked candidate |
| 6.2 | Blocked/not executed: no successful frozen gate; screening is not acceptance |
| 6.3 | Blocked/not executed: frozen/server/evaluator/package prerequisites unmet |
| 6.4 | Unmet: retrieval quality acceptance cannot be declared |

Minimal standard closure, **proposed only**:

1. Preserve the decision, evidence, protocols/receipts and task states; validate
   the change. No additional inference is needed for administrative closure.
2. On later explicit archive authorization, display the eight unfinished tasks
   and assess all four delta capabilities: hybrid-retrieval, lexical-retrieval,
   markdown-chunking and rag-evaluation-corpus.
3. Choose **Archive without syncing**. These deltas preserve an experimental
   plan, including the rejected reranker, and must not automatically become
   accepted main specs. Retain them as archived history. Existing opt-in code
   remains experimental; archive does not accept or deploy it.
4. Use standard archive with its incomplete-task confirmation. A later interactive
   CLI equivalent is `openspec archive retrieval-quality-improvement --skip-specs`
   (`openspec.cmd` in this PowerShell environment). Keep validation enabled.
   Do not use `--no-validate`, fabricate `[x]`, or manually move the directory
   to bypass the workflow. The confirmation comes from
   `.agents/skills/openspec-archive-change/SKILL.md`, step 3; it is not requested
   or granted in this review. **Do not run archive now.**
5. Record archive as negative / reranker rejected / eight incomplete tasks /
   specs not synced, with quality acceptance still unmet.

After closure, separately authorize exploration of a new retrieval approach
using preserved diagnostics: distinguish structural top-5 feasibility,
candidate recall and ranking loss; assess resource cost before choosing an
implementation. Only after that design decision create a distinct change and
preregister its protocol. Historical evidence requires disclosure, frozen
expectations/thresholds remain unchanged and independent validation needs its
own preparation. This administrative plan authorizes no new experiment.
