# Retrieval quality development result, 2026-10-16

**Negative development result; quality acceptance remains open.**
All 36 preregistered combinations ran only on tuning, with repeated identical
ranks/scores/counts. [Full grid and selection](retrieval-quality-tuning-grid.json)
includes ablations, per-case legacy losses, report fingerprints, local warm
latency and peak memory. Detailed per-case witness/branch/final diagnostics and
cold/warm measurements remain in the referenced local report files under
`data/retrieval-quality-improvement/grid/`.

| Chunk algorithm | Literal policy | Best single-question tuning hits |
| --- | --- | --- |
| Legacy v1 | v1 | 6/9 |
| Legacy v1 | v2 | 6/9 |
| Packing v2 | v1 | 5/9 |
| Packing v2 | v2 | 5/9 |

The preregistered selection rule chooses legacy chunking/literal policies,
S=10, L=1, RRF=60, query k=6. No legacy single-question hits are lost by this
selected development variant; its misses remain q02, q03 and q07. Higher total
hit count takes precedence over individual losses; tied variants without losses
precede variants with losses, then follow-up, policy complexity and branch
limits apply. Selection reproduced with reversed candidate order. Every variant
retains the same nine-case tuning denominator; case losses are reported without
excluding a variant. No holdout information informed selection.

Packing is structurally feasible: q03 minimum=5, compared with legacy minimum=6,
and the required adjacent prose/code pair is source-backed in one chunk. It does
not produce the required aggregate retrieval improvement. The new inventory has
674 chunks, real-tokenizer maxima 447 body/467 input tokens, and fully rebuilt
E5 vectors. Legacy output is byte-identical; repeated new semantic and lexical
snapshots are byte-identical. Literal-only builds preserve base/provenance and
raw vectors. Source inputs and historical snapshots/baselines remain unchanged.

**Stop condition 5.2 applies:** best eligible tuning 6/9 is below 8/9. Even
perfect historical holdout would yield at most 9/12=75%, below 11/12. No lock,
final frozen candidate comparison, target-server acceptance or independent
retrieval validation was performed. Existing historical exposed holdout results
are not independent validation. No closed validation package was opened or run.
Development timing/memory and passing tests cannot establish server acceptance.

Tasks 1.2–1.3 remain open at the owner's request: evaluator appointment is
deferred, and reviewed closed questions, commitments and evaluator validation
receipt have not been supplied. Task 5.3 and tasks 6.1–6.4 remain open because
the development threshold failed. Independent validation also requires successful
frozen/server gates and the evaluator/package. The change is not archived;
retrieval quality MVP acceptance is not achieved.

Continuation requires review of an expanded experiment plan under the design's
stop condition, before further candidates. Frozen expectations, evidence scoring
and budgets cannot be weakened to obtain acceptance. See the
[workflow and verification record](retrieval-quality-improvement.md),
[protocol](retrieval-quality-experiment-protocol.md),
[development diagnosis](retrieval-quality-development.json),
[packing feasibility](retrieval-quality-packing-feasibility.json),
[rebuild audit](retrieval-quality-build-report.json) and
[literal build audit](retrieval-quality-literal-builds.json).

Verification: full application suite **718 passed, 7 platform skips**; one
existing Starlette/httpx deprecation warning. Typing passed all eight changed
source modules, existing frozen-package integrity validation and OpenSpec strict
validation passed. [Verification receipt](retrieval-quality-verification.json)
records implementation hashes, all 36 report hash checks, repeat selection,
full original source coverage and serialized real-token counts. This receipt
is a development record, not an acceptance lock.


## V2 server screening decision, 2026-10-20

**Negative result: STOP before lock or acceptance.** Archived first-run metrics:
legacy 6/9 (warm mean 0.009478 s), control 6/9 (0.009546 s), reranker 4/9
(2.446002 s): **258.071122x** legacy, against mandatory <=2x and >=8/9.
Reranker gains q07 but loses q01/q12/q19 against both controls; q02 remains a
partial-coverage miss. Docker exit=0, no OOM/cap violation. First/warm results
match; second fresh repeats are absent, so full 5.7 reproducibility is incomplete.

[Separate v2 decision and evidence analysis](retrieval-quality-result-v2.md)
and [machine-readable audit](retrieval-quality-evidence-audit-v2.json) record
archive SHA-256, integrity, per-case transitions, resource measurements and
limitations. Task 5.8 is closed as a negative report. Task 5.7 remains open;
5.3 and 6.1-6.4 are blocked by failed development gates. Tasks 1.2-1.3 still
lack evaluator/package/actual validation evidence. Progress: 17/25.
No repeat inference, historical holdout, independent validation or next
experiment was executed during this review. Quality acceptance remains open.
Owner decision, 2026-10-20: experiment v2 ends negatively; cross-encoder
reranker rejected. No further v2 runs. Standard archive completed on 2026-10-20
at `openspec/changes/archive/2026-10-20-retrieval-quality-improvement/`, preserving
17/25 task states and eight unfinished tasks, without delta-spec synchronization.
The [v2 report](retrieval-quality-result-v2.md) records the archive checks. A new approach
requires separately authorized design and a new protocol.

The v1 report above is unchanged byte-for-byte as a prefix. Complete original
bytes are also preserved in [the frozen v1 report](retrieval-quality-result-v1-frozen.md),
SHA-256 `49008ac640564014fc4e2e5d4fabaaa766a472102ae671f35f11a9c607f58a42`.
This explicitly requested addendum changes the historical result.md path hash;
existing receipts retain the original commitment and were not rewritten.
Protocol v2, model, retrieval policy, thresholds and frozen inputs are unchanged.
Audit documentation hashes record the earlier evidence-review snapshot, before
this owner-decision clarification; raw evidence and receipts remain unchanged.
