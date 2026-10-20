# Retrieval quality experiment protocol v1

Preregistered 2026-10-16, before implementation or candidate inference.
The accompanying `retrieval-quality-protocol-receipt.json` commits this file's
SHA-256 and protected input hashes against the saved technical handoff.

## Allowed data and disclosure

Only frozen live tuning (nine answerable single questions and one separate
follow-up) may inform diagnosis, experiments or selection. Expectations, source
reference, splits and evidence protocol v1 stay unchanged. Historical holdout
has been exposed in previous reports: it is permitted only in the final locked
comparison, never for selection, targeted tests or another tuning cycle.
Original Markdown may inform general structural rules without case/page/path/
offset conditions. Synthetic structural tests do not establish live quality.
No synonyms, morphology, rewriting, reranker, model switch or larger budgets.

## Exhaustive grid and selection

Exactly 36 combinations: chunk policy `markdown-chunking-1` or
`markdown-chunking-2`; literal policy 1 or 2; semantic candidates 10, 40, 120;
lexical candidates 1, 10, 20; RRF constant 60; query k=6, evidence scorer k=5.
No additional settings search. Preserve API defaults 10/10/60/6 and pure
semantic behavior. Record limits-only, packing-only, literals-only and combined
ablations against legacy 10/1/60, every combination and exclusion reason.

Among candidates passing mandatory checks, maximize tuning single-question
hits; then prefer no lost legacy tuning hits (a boolean criterion, not loss
count); then maximize follow-up hits; then minimize changed policies; then
minimize S+L; then minimize S; then lexicographically compare policy IDs.
Case-level hit-to-miss transitions are reported by ID, never exclusion gates.
If all tied candidates have losses, advance to the next tie-break.

## Mandatory checks and measurements

Reject integrity or functional failures: altered protected inputs, unknown
versions, nonreproducible IDs/ranks/scores/counts, stale vectors, source namespace
or provenance mismatch, lost source coverage, changed base schema, changed
legacy output/ranking, changed defaults or HTTP health. Numeric chunk budgets
remain target=350, maximum=450, overlap=50, full E5 input=512 with real local
tokenizer and no truncation. All snapshots/reports go to separate paths under
`data/retrieval-quality-improvement/`; reject input/output aliases. Rebuild all
vectors for changed inventory; literal-only builds must preserve every raw
embedding and base/provenance value. Verify repeat identities and failure
preservation. Retain original snapshots for rollback.

Record build duration/disk increment, initialization, first query, second-pass
warm per-query latency and peak RSS separately, with environment/model/tokenizer/
policy/settings fingerprints. Sequential isolated workers, offline assets, no
concurrent old/new E5, no cache clearing; cold means first query with lazy load.
Development measurements cannot establish server acceptance.

Target server: i5-14400, 15 GiB, CPU only, Linux/Docker, 4 CPUs/5 GiB cap.
Two identical offline locked runs, sequential legacy comparison in the same
environment; no errors/OOM, matching ranks/scores/counts, selected hybrid warm
arithmetic mean <=2x legacy. Wiki.js: >=20 baseline and >=20 load samples,
zero errors; p95 <=2x baseline using sorted samples and nearest-rank
`ceil(0.95*N)-1` indexing. Record timestamps, sample counts, raw durations,
RSS, swap, disk and available memory. Short samples do not establish sustained
production performance. All resource checks are mandatory exclusion gates.

## Stop conditions and final gate order

1. Verify this protocol hash and handoff hashes before development tasks 2–5.
2. If generic packing does not join tuning q03 ranges [6504,6579) and
   [6579,6595) within unchanged budgets/heading, or minimum remains >5, record
   failure and stop that branch for plan review; no special join.
3. If best eligible tuning <8/9, record negative development result and stop
   before final/independent validation; request plan review.
4. Lock code revision, settings and snapshot/model/tokenizer/policy hashes;
   verify identical repeated tuning ranks/scores/counts.
5. One final frozen three-mode comparison: denominator 12=9 tuning+3 exposed
   holdout, >=11/12 required. Follow-up/synthetic/answerless remain separate.
   Failure leaves gate open and blocks subsequent acceptance, with no retuning.
6. Actual repeated target-server integrity/regression/resource acceptance.
   Failure or absent evidence blocks independent validation.
7. Only then independent evaluator opens and runs the committed closed package.
   Any prerequisite failure preserves it unopened and unused.

## Independent evaluation

Evaluator must not select policies/configuration or use the historical miss list
to choose questions. No evaluator is appointed by this document. Absence blocks
independent acceptance, never development after the first gate.
Package resides outside developer-accessible tuning paths: >=20 new manually
reviewed live single-question holdout cases, covering prose, commands, tables,
identifiers and composite evidence; no duplicates/paraphrases of old questions.
Also >=2 follow-ups and >=3 refuse/clarify cases, plus existing validator's
required tuning/synthetic coverage. Commit questions/manifest/reference hashes
and semantic review before retrieval. Evaluator performs existing offline
package validation and saves a separate receipt without disclosing questions
or expectations to the developer. Independent retrieval uses `--split holdout`;
validator-support tuning cases never enter its denominator.

Require ceil(0.9*N) live single-question hits, with numerator/denominator, misses,
95% Wilson interval and disclosure of same-source-corpus generalization and
small sample limitations. Identical reproducibility repeat only; a failed check
requires a new protocol/package for a future iteration. Frozen and independent
denominators never mix. Quality acceptance requires all frozen, independent,
integrity, functional and server gates. Do not archive until all mandatory
acceptance criteria pass.
