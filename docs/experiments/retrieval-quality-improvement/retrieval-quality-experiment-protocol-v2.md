# Retrieval quality experiment protocol v2

Planning revision, 2026-10-16. This is the bounded continuation after review of
v1 stop condition 5.2, not an execution receipt or acceptance lock. No reranker
implementation, model download or inference is performed by this revision.
Before implementation, task 5.4 commits this file's SHA-256, code/worktree
identity and protected input hashes in a separate v2 receipt. Before inference,
task 5.5 adds verified local model/tokenizer/runtime identities. A mismatch or
missing receipt blocks execution; a protocol change requires review and a new
version, never a silent edit to the committed protocol.

## Preserved history and allowed data

V1 remains `docs/retrieval-quality-experiment-protocol.md`, SHA-256
`c41b1156d04cc368e3db4f0de8ffbaf20fb250c7a56429230d78d7abe2ea2e5a`.
Preserve its receipt, all 36 candidate reports, grid, ablations, development
diagnosis, build/verification records and negative result (best 6/9). V2 does
not reopen that grid or retrospectively select a different v1 winner.

Only the same nine frozen live answerable tuning single questions inform this
experiment. The existing tuning follow-up is reported separately using the
unchanged evaluation adapter (previous question + newline + current question,
no answers). Synthetic structural tests are permitted, never quality evidence.
Historical exposed holdout is not read, run or used for diagnosis, targeted
tests, model choice, candidate limits, budgets or selection in development.
Closed validation remains unopened. Frozen questions, splits, reference,
expectations, scorer protocol v1 and original source provenance never change.

## One model artifact, chosen before inference

- Repository: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`.
- Immutable revision: `1427fd652930e4ba29e8149678df786c240d8825`.
- Weights: only `model.safetensors`, FP32; published SHA-256
  `5daeca2481a76b5976a2bdc32f0a78532b6716da4f8cd3ff59460ef8d2f359b4`.
- Config and fast tokenizer files come from that same revision:
  `config.json`, `tokenizer.json`, `tokenizer_config.json`,
  `special_tokens_map.json`; retain model card/license metadata with the bundle.
  Published tokenizer SHA-256:
  `62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626`.
  Verify every local file hash and record the complete bundle manifest before
  any inference. No moving `main`, pickle weights, ONNX/OpenVINO export,
  quantization, fine-tuning, alternate model or parameter search.

Rationale: the upstream model card labels Apache-2.0 and explicitly includes
Russian (`ru`). It is a multilingual passage-ranking cross-encoder; its
12-layer, width-384 architecture and approximately 471 MB FP32 weight file
bound the additional artifact size. This is a compact candidate, not a claim
of smallest possible model, Russian-domain accuracy, runtime RSS or CPU speed.
Its standard XLM-R classification architecture can use the existing pinned
PyTorch/Transformers stack and a fast tokenizer without a new service or
dependency. Offline loading is part of the contract: explicit local path,
`local_files_only=True`, `trust_remote_code=False`, `use_safetensors=True`,
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, no network in inference workers.
Missing/incompatible assets stop the experiment; no network or RRF fallback.

Primary sources inspected for planning (metadata only; weights not fetched):

- [Model card and language/license metadata](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1/blob/1427fd652930e4ba29e8149678df786c240d8825/README.md).
- [Pinned revision/config/tokenizer](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1/commit/1427fd652930e4ba29e8149678df786c240d8825).
- [Weight artifact](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1/blob/1427fd652930e4ba29e8149678df786c240d8825/model.safetensors).
- [Transformers offline loading](https://huggingface.co/docs/transformers/v4.57.3/installation#offline-mode).

## Fixed inventory, union and controls

Reuse read-only `data/hybrid-live.db`: legacy `markdown-chunking-1`, literal
policy 1, SHA-256
`87fa5e9b2af30044a509d19c16440db2545d5941f0eab3d3795a9e6af7d2fa44`.
Use the existing corresponding legacy synthetic snapshot only for separate
structural checks; verify all handoff hashes from the v1 receipt.
No new chunks, vectors, FTS policy, inventory packing or rebuild.

The saved tuning-only `grid/c1-l1-s120-l1.json` diagnostics already show full
q02 (minimum=3) and q07 (minimum=1) evidence in branch union and final-ranking
loss. Thus use semantic S=120 and lexical L=1, RRF constant 60, final k=6.
This is the smallest already tested semantic limit in the declared v1 grid
with the required coverage, not a proof of global minimum; no search of
intermediate limits is authorized. Literal v2 and L=20 add no required recall
for these failures. Rerank all distinct branch candidates, at most 121 chunks,
before any RRF top-k cutoff. Deduplicate only by chunk ID; preserve different
chunks from the same page. No evidence-aware selection, page quota, neighbours,
query expansion, score blending, literal boosts or dynamic candidate budget.

Exactly three comparison arms, one experimental candidate:

1. Historical legacy RRF: same legacy snapshot, S=10/L=1/RRF=60/k=6.
2. Limits-only RRF control: same snapshot, S=120/L=1/RRF=60/k=6.
3. CPU cross-encoder: exactly the union of arm 2, fixed artifact/settings below.

Retain existing semantic-only/lexical-only comparisons and historical reports;
the new arm is separately named and never relabelled as RRF. Defaults remain
10/10/60/6, pure semantic behavior and HTTP startup/health stay unchanged.
No development holdout comparison; final frozen comparison remains after lock.

## Exact input, token and inference budgets

Each model input is a pair: the supplied question and the complete stored
`StoredChunk.search_text`, unchanged. No E5 `query:`/`passage:` prefixes,
instructions, extra metadata/history, summaries or text normalization are
added. The evaluator-only follow-up concatenation above is the sole exception
to ordinary question-only search. Existing source/generated metadata remains
attached to the returned original chunk; generated text never counts as evidence.

Count using the pinned cross-encoder fast tokenizer, separately from E5:
question <=128 tokens without special tokens; complete pair <=512 tokens
including the tokenizer's four pair special tokens. Passage allowance is the
remaining `508 - question_tokens`, not a fixed E5-body token allocation.
Batch size=1, `padding=False`, `truncation=False`: process each complete pair
at its actual token length, at most 512; do not pad pairs to 512. Validate lengths and
pair framing before inference. Preflight every candidate of every permitted
tuning question/follow-up before any quality inference. Any overflow stops the
whole experiment for review, including overflow in an irrelevant candidate;
do not drop candidates, shorten questions, truncate chunks, window text or
raise budgets. E5/chunk budgets remain 350/450/50/512. Different tokenizers mean
legacy E5 compliance does not establish cross-encoder input feasibility.

CPU only, FP32, eager attention, evaluation/inference mode, no compilation or
autocast, seed=0, deterministic algorithms enabled, intra-op threads=4,
inter-op threads=1, tokenizer parallelism disabled. Use existing pinned
`torch==2.7.1+cpu`, `transformers==4.57.3`, `tokenizers==0.22.2`;
record actual versions/builds plus Python, CPU, OS and container identity.
Sort candidates by chunk ID for inference; score is the single finite raw
classification logit, descending, exact ties by chunk ID ascending. No
sigmoid calibration, thresholds, epsilon ties or fusion with other scores.
Return original chunks/provenance, branch scores/ranks, RRF score and separately
labelled reranker score/model/policy identity; no score is answer confidence.

Two fresh sequential runs of each arm in the same environment, one first pass
and one warm pass per run in frozen case order. Record union IDs/input hashes,
token maxima, every candidate logit/order, top-5 evidence coverage, ranks,
counts and all individual transitions relative to both controls. Repeat
union/input identities and serialized finite scores/ranks/counts must match
exactly within the same environment; mismatch stops without changing settings.
No claim of bit equality across different platforms; each target environment
must independently pass identical repeats. Latency/RSS are measured, not
required to be byte-identical. No response-score cache, no cache clearing.

## Resource and integrity gates

Development resource screening uses only tuning under the same target envelope:
i5-14400 Linux/Docker, CPU only, 4 CPUs and 5 GiB memory cap. It is not final
target-server acceptance and does not consume any holdout. Run arms in isolated
sequential workers, keeping E5 and the cross-encoder resident together within
the candidate worker. Chunking, embedding and FTS rebuilds are not performed
in v2; mark their build durations, build-only RSS and build disk increments
N/A (reused read-only snapshot), never zero or missing required measurements.
Keep v1 build records as historical evidence, not v2 measurements.
Record whole-worker peak RSS and container memory peak,
swap/available memory, bundle disk increment, model loading/init durations,
first-query, per-query warm
latency and time spent in branches/tokenization/reranking separately. Compare
end-to-end warm arithmetic mean over the nine single questions against arm 1
in the same environment (follow-up separately). Both repeated runs must have
no errors/OOM, respect the 5 GiB cap and warm mean <=2x legacy arm 1. Missing
measurements are an incomplete gate, never a pass. No resource threshold is
relaxed to accommodate this model; 121 CPU pairs may fail the existing gate.

Reject changed protected hashes, provenance/namespace mismatch, stale vectors,
corrupt/unknown policy/model identity, incomplete union, budget violations,
nonfinite scores, network access/fallback, nonreproducible repeats or changes
to legacy RRF/defaults/pure semantic/HTTP health. Keep all v1 functional gates.
Reports/settings/receipts use new `data/retrieval-quality-improvement/reranker-v2/`
and `docs/retrieval-quality-*-v2.*` paths, rejecting input/output aliases. V1
and protected input files must remain byte-identical before and after execution.

Final target-server acceptance remains after lock and frozen gate, with the
same repeated resource checks, explicit N/A build metrics (no chunking,
embedding or FTS rebuild), measured model loading/init, latency, RSS and disk,
and Wiki.js >=20 baseline/>=20 load samples,
zero errors, p95 <=2x baseline, nearest-rank `ceil(0.95*N)-1` indexing. Include
sample counts, raw durations and short-measurement limitations. Earlier tuning
resource screening cannot replace this final gate.

## Decision, stop and final acceptance order

No best-of-many selection: accept the sole candidate for lock consideration
only if all mandatory development gates pass and complete evidence Hit@5 on
the unchanged nine single-question tuning cases is >=8/9. q02 requires all
three evidence chunks in top-5; q07 requires one. Legacy q03 remains impossible
at minimum=6 and remains in denominator as a miss, so 8/9 requires every other
case to hit. All individual hit-to-miss transitions against both controls,
partial/rank losses and follow-up regressions are registered even when totals
improve; case-level regressions are reports, not additional exclusion gates.

At <8/9 or any mandatory input/integrity/reproducibility/resource failure,
save the negative/incomplete report and stop before lock/final/independent
validation. No replacement model, L20/v2 fallback, extra grid or retuning;
further work requires another reviewed protocol. Identical reproducibility
repeats are the only permitted additional executions.

If development gates pass, preserve the existing order:
lock (code/worktree, settings, both model/tokenizer identities, snapshot and
protocol hashes) -> one frozen v1 comparison (scorer protocol v1, denominator
12=9 tuning+3 exposed holdout, >=11/12) -> actual repeated target-server
acceptance -> independent evaluator's committed closed validation >=90%.
Semantic/lexical/RRF and explicitly labelled reranked results remain distinct.
Historical holdout is permitted only for that final locked report, never for
tuning. Failure/incomplete prerequisite blocks later gates, leaves acceptance
open and preserves closed validation unopened and unused. Independent package
requirements, >=20 new reviewed live cases, separate follow-up/answerless
reporting, Wilson interval and no retuning after validation remain those of v1.
Experiment protocol v2 is not a new evidence scorer/corpus version and does
not weaken frozen >=11/12 or claim generalization from development >=8/9.
