# Retrieval quality v2: implementation ready, screening pending

2026-10-19. **Incomplete development evidence; no acceptance lock.**

Tasks 5.5 and 5.6 are complete. The existing task-5.4 commitment was extended
with bundle/runtime verification, not recreated. The exact pinned FP32 bundle
passed published SHA-256 and guarded offline loading checks; all six local
assets are excluded from Git. See the [receipt](retrieval-quality-protocol-receipt-v2.json)
and [bundle/CLI workflow](retrieval-quality-offline-bundle-v2.md).

The new opt-in module ranks the entire S120/L1 legacy union with the pinned
CPU cross-encoder, preserving original chunks, branch/RRF scores and provenance.
Default RRF, semantic and HTTP behavior remain covered by regression tests.
The global live-answerable tokenizer preflight passed for 1,201 pairs across
nine single questions and the separate follow-up: maximum 469/512 pair tokens
and 25/128 question tokens. The application CLI additionally preflighted all
14 tuning cases, including separate synthetic/answerless cases, for 1,682 pairs
with the same maximum and no overflow. These are input-feasibility results.

**Task 5.7 is pending:** the available execution environment is Windows without
Docker. No target-server SSH host/alias or connection details have been supplied.
The three-arm, two-fresh-repeat experiment and mandatory Linux/Docker 4 CPU / 5 GiB
resource screening have not run. No cross-encoder live quality inference,
reranked Hit@5, repeat-score comparison, warm latency ratio, combined resident
model/container peaks or target-server resource pass is claimed. Operator-reported
free disk/RAM and zero swap I/O are preparation observations only.

Task 5.8 remains open because neither tuning quality nor the mandatory screening
evidence exists. The candidate has not passed or failed the >=8/9 quality test.
Do not substitute Windows measurements, add another model/limits/policy, or
consume historical holdout or closed validation. Resume the preregistered
task 5.7 on the target environment with the same artifacts and fixed settings.

Tasks 5.3 and 6.1–6.4 remain open. The order remains successful development
gates → lock → frozen v1 >=11/12 → actual target-server acceptance → independent
>=90%. Scorer/corpus protocol v1, tuning denominator 9 (including structural
q03 miss), frozen denominator 12, protected inputs, v1 negative result and all
36 historical reports remain unchanged. Historical holdout and closed validation
were not used by this continuation. Retrieval quality MVP acceptance is open.
