# Retrieval quality workflow

Development protocol: [preregistration](retrieval-quality-experiment-protocol.md),
[hash receipt](retrieval-quality-protocol-receipt.json).
Historical inputs remain read-only; all new outputs are under
`data/retrieval-quality-improvement/`. Independent evaluator/package are not
available. Tasks 1.2 and 1.3 remain open; development may proceed.

## Independent package procedure (evaluator only)

Prepare and semantically review the closed package outside developer-accessible
paths with all coverage required by the existing validator, including separate
support tuning/synthetic cases. Commit questions/manifest/reference hashes before
retrieval and save the semantic-review and offline-validation receipts. Do not
send closed questions/expectations to the developer. From `app/`:

```sh
python -m app.evaluation --questions /closed/questions.yaml --manifest /closed/manifest.json --snapshot /closed/wiki-documents.json --fixtures /closed/fixtures.json > /closed/integrity-receipt.json
```

Only after successful lock, frozen v1 and actual target-server gates:

```sh
python -m app.hybrid_retrieval evaluate --questions /closed/questions.yaml --manifest /closed/manifest.json --snapshot /closed/wiki-documents.json --fixtures /closed/fixtures.json --index /locked/live.db --synthetic-index /locked/synthetic.db --model-path /locked/model --split holdout --semantic-candidates S --lexical-candidates L --rrf-constant 60 --top-k 6 > /closed/retrieval-report.json
```

Use locked S/L values. Only new live single-question holdout cases enter the
independent denominator; follow-up, answerless, synthetic and support tuning
remain separate. Report ceil(0.9*N), misses and Wilson 95% interval. These are
instructions, not evidence that evaluator validation has run.

## Legacy tuning reproduction and diagnostics

[Development report](retrieval-quality-development.json) records protected
fingerprints, witness IDs/ranges and verified exact ranks/scores/hits against
the saved baseline for all 14 tuning cases in each of three modes. Full local
report: `data/retrieval-quality-improvement/legacy/tuning.json`. No candidate
holdout inference was run.

q02 has minimum=3 but candidate loss; q03 has minimum=6 and candidate loss;
q07 has minimum=1 with branch coverage but final ranking loss. Inventory
coverage proves structural availability, never a retrieval hit. Minimum search
uses original source intervals with namespace/document identity, excludes
generated text, reports witness and bounds, and returns unknown on search budget
exhaustion. Branch coverage is the actual union requested by hybrid; standalone
mode coverage is its returned candidate list. Final coverage is always top five.

Frozen single-question denominator is 12 (9 tuning + 3 exposed holdout).
11/12=91.67% passes; 10/12=83.33% fails. Legacy 6/12 needs a net five new hits.
One structurally impossible case gives an aggregate upper bound of 11/12,
so q03 alone does not prove the aggregate target impossible. Even a minimum
<=5 can miss through candidate selection or final ranking. Query default k=6
does not alter evidence scorer k=5; the sixth result never repairs Hit@5.

Legacy reproduction, from `app/` with offline environment flags:

```sh
python -m app.retrieval_comparison evaluate --questions ../eval/questions.yaml --manifest ../eval/manifest.json --snapshot ../data/eval/1/wiki-documents.json --fixtures ../eval/fixtures/wiki-documents.json --index ../data/hybrid-live.db --synthetic-index ../data/hybrid-synthetic.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --split tuning --semantic-candidates 10 --lexical-candidates 1 --rrf-constant 60 --top-k 6 > ../data/retrieval-quality-improvement/legacy/tuning.json
```

Targeted diagnostics/evaluation/comparison/hybrid tests: 33 passed, including
minimum=6, missing/generated/namespace mismatches, overlapping ranges, unknown
bounds, branch loss, cover<=5 ranking loss and the sixth-result cutoff.

## Packing build and rollback

[Feasibility report](retrieval-quality-packing-feasibility.json): real E5 tokenizer
joins the q03 pair, exact minimum=5, maxima 447/467, 674 chunks; legacy output
SHA-256 matches `data/chunks-live-final.json` byte for byte. Structural success
does not establish a hit. Packing/structure/CLI tests: 36 passed, one Windows
symlink skip. Storage/semantic/retrieval tests: 147 passed. Base schema stays v1;
both known algorithms are accepted and unknown algorithms rejected.

From `app/`, with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, create the
separate output directory first. Run the same pipeline for synthetic using
`../eval/fixtures/wiki-documents.json` and `*-synthetic` output names:

```sh
python -m app.chunking --input ../data/eval/1/wiki-documents.json --output ../data/retrieval-quality-improvement/packing/chunks-live.json --tokenizer-path ../data/tokenizers/614241f622f53c4eeff9890bdc4f31cfecc418b3 --algorithm-version markdown-chunking-2
python -m app.index_storage --input ../data/retrieval-quality-improvement/packing/chunks-live.json --output ../data/retrieval-quality-improvement/packing/storage-live.db
python -m app.embeddings build --input ../data/retrieval-quality-improvement/packing/storage-live.db --output ../data/retrieval-quality-improvement/packing/semantic-live.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3
python -m app.lexical_storage build --input ../data/retrieval-quality-improvement/packing/semantic-live.db --output ../data/retrieval-quality-improvement/packing/hybrid-live.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3
```

Rollback: explicitly use original `../data/hybrid-live.db` and
`../data/hybrid-synthetic.db`, legacy settings 10/1/60/6, or original semantic
snapshots for pure semantic queries. Never overwrite them. The legacy tuning
comparison above executed this rollback path offline. Chunk policy defaults
remain legacy; use `--algorithm-version markdown-chunking-1` to reproduce it.

[Build report](retrieval-quality-build-report.json) records full E5 rebuild and
disk costs, complete new vector inventory, repeated identical semantic/lexical
bytes and preservation on failure. Both namespaces were built offline with
the documented pipeline APIs. No old vectors were reused for new IDs.

## Literal policies and rollback

Legacy v1 remains the default. Build v2 explicitly into another snapshot:

```sh
python -m app.lexical_storage build --input ../data/semantic-live.db --output ../data/retrieval-quality-improvement/legacy-literal-2/hybrid-live.db --literal-policy-version 2
python -m app.lexical_retrieval query --index ../data/retrieval-quality-improvement/legacy-literal-2/hybrid-live.db --question 'charge_device_id clear_device_id'
```

Use `--literal-policy-version 1` and `legacy-literal-1` for explicit v1 build;
use packing semantic inputs for packing variants and repeat for synthetic.
Query dispatch reads the snapshot metadata; no implicit policy upgrade.
Rollback is the original hybrid paths or the separately reproduced v1 paths.
[Literal build report](retrieval-quality-literal-builds.json) records eight
actual offline CLI builds/queries (both algorithms/policies/namespaces), base
and raw-vector preservation, original input hashes and legacy v1 byte equality.
All queries passed in fresh processes with heavy embedding imports blocked and
absent model assets. Lexical/storage/hybrid/comparison tests: 86 passed, one
Windows symlink skip. Typing passed seven changed source modules.

## Tuning grid and selection

The grid uses fresh sequential offline hybrid workers with `--split tuning`,
both literal policies, both chunk inventories, S={10,40,120}, L={1,10,20},
RRF=60 and query k=6. Each worker repeats identical inputs and rejects changed
ranks/scores/counts. Full per-case diagnostics, witness/branch/final coverage,
initialization/first/warm latency and process peak memory are saved under
`data/retrieval-quality-improvement/grid/`. Artifact fingerprints bind reports
to their policies/settings. The selection helpers reject mixed splits,
fingerprints, policy/settings identities and changed denominators. Ten targeted
selection tests passed; losses are an explicit boolean tie-break after hit count,
and never exclude an otherwise eligible candidate. Actual server resource
acceptance remains a later mandatory gate; local measurements cannot replace it.

An example tuning worker invocation (use each declared S/L combination and the
matching `legacy|packing-literal-1|2` directory):

```sh
python -m app.retrieval_comparison worker --mode hybrid --questions ../eval/questions.yaml --manifest ../eval/manifest.json --snapshot ../data/eval/1/wiki-documents.json --fixtures ../eval/fixtures/wiki-documents.json --index ../data/retrieval-quality-improvement/packing-literal-2/hybrid-live.db --synthetic-index ../data/retrieval-quality-improvement/packing-literal-2/hybrid-synthetic.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --split tuning --semantic-candidates 120 --lexical-candidates 20 --rrf-constant 60 --top-k 6
```

Evaluator appointment is deferred by the owner; tasks 1.2–1.3 remain open.
Package preparation, semantic review, fingerprints and evaluator integrity
receipt have not been supplied. The documented procedure alone does not close
these tasks.

All 36 combinations completed. [Negative result and gate statuses](retrieval-quality-result.md):
best tuning 6/9; maximum attainable frozen aggregate 9/12 even with perfect
holdout. Stop condition 5.2 prevents lock/final acceptance. The full
[grid report](retrieval-quality-tuning-grid.json) records all combinations and
ablations; no candidate holdout or independent queries were executed.

Final verification: full suite 718 passed/7 platform skips with one existing
Starlette/httpx warning; mypy passed all eight changed modules. Frozen package
integrity validator and strict OpenSpec validation passed. All nine protected
handoff hashes, protocol hash, baseline hash and 36 worker report hashes were
checked again. Every new serialized chunk's counts were verified with real E5
tokenizer, and all original source positions of both namespaces are covered.
See [verification receipt](retrieval-quality-verification.json).
