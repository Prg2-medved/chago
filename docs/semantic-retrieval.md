# Semantic retrieval

## CPU environment

Install `app/requirements.txt` in a clean Python 3.12 environment before runtime.
The requirements pin Sentence Transformers 5.1.2, Transformers 4.57.3, NumPy
2.2.6 and PyTorch 2.7.1+cpu; tokenizers remains 0.22.2. The CPU wheel index is
explicitly configured. No CUDA packages are required.

```powershell
python -m venv tmp/semantic-env
tmp/semantic-env/Scripts/python.exe -m pip install -r app/requirements.txt
tmp/semantic-env/Scripts/python.exe -m pip check
```

The existing Dockerfile installs these same requirements. Libraries are not loaded
by HTTP startup or storage-only operations. Model assets are not startup requirements.

## Explicit embedding configuration

Python does not load `.env` automatically: export variables in the calling shell.
Compose passes the same values to its app service through the existing `/data` mount.

| Variable | Default |
| --- | --- |
| `EMBEDDING_MODEL_PATH` | `/data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| `EMBEDDING_MODEL_ID` | `intfloat/multilingual-e5-small` |
| `EMBEDDING_MODEL_REVISION` | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| `EMBEDDING_BATCH_SIZE` | `16` |
| `EMBEDDING_CPU_THREADS` | `4` |

Use a host-local model path when running outside Compose. Batch size and CPU threads
must be positive integers. Empty paths and unsupported model identities are rejected
with safe configuration categories; values are not included in diagnostics.
Only this model and revision are supported. Changing the identity requires a coordinated
tokenizer contract update and rebuilding semantic snapshots.

## Preinstall model assets

Obtain only the following files from the immutable
[official model revision](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3):
`model.safetensors`, `config.json`, `modules.json`, `sentence_bert_config.json`,
`1_Pooling/config.json`, `tokenizer.json`, `tokenizer_config.json`,
`special_tokens_map.json`. Preserve relative paths under `EMBEDDING_MODEL_PATH`.
Download during installation only. The committed `app/app/embedding_manifest.json`
contains SHA-256 hashes calculated from these revision-pinned files on 2026-10-09;
its tokenizer hashes match `chunk_tokenizer.ASSET_HASHES`.

For example, a separate provisioning script can download each named file from
`https://huggingface.co/intfloat/multilingual-e5-small/resolve/<revision>/<filename>`
and compare its SHA-256 against the committed manifest before placing it in the
model directory. Do not regenerate the manifest from an arbitrary local model.
The eight-file set totals approximately 488 MB. A full Hub snapshot,
`sentencepiece.bpe.model`, pickle weights and alternative exports are unnecessary.
Runtime must use fast tokenization and safetensors exclusively.

## Encoder contract

`LocalEncoder(EmbeddingSettings(...))` verifies all assets immediately; heavy
libraries and the model load lazily on first inference. Inputs use exactly
`query: <question>` and `passage: <title>\n<headings joined by ' > '>\n<search_text>`.
Complete inputs, including special tokens, must fit 512 tokens; overflow and
whitespace-only questions fail without truncation. Passage counts must match
the stored chunk counts. Backend token IDs are checked against LocalE5 before
inference. Results are finite, normalized little-endian float32 vectors of
dimension 384. Explicit batches and CPU threads control runtime resources.

Runtime sets Hub/Transformers offline flags, prohibits remote code, requests
`use_safetensors=True` and a fast tokenizer, and never falls back to pickle.
Safe categories are `embedding_identity`, `embedding_assets`,
`embedding_configuration`, `embedding_tokenizer`, `embedding_budget`,
`embedding_token_counts`, `embedding_query`, `embedding_backend`,
`embedding_inference`, and `embedding_vectors`. They do not include backend
exception text, questions, source text or credentials.

## Build and format

From `app/`, run:

```sh
python -m app.embeddings build --input /data/storage.db --output /data/semantic.db --model-path /data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3
```

From the project root, the Compose equivalent is:

```sh
docker compose run --rm --no-deps app python -m app.embeddings build --input /data/storage.db --output /data/semantic.db
```

The input opens read-only and retains its bytes. Output must be distinct from input
and outside model assets, including resolved paths and existing hard links. Build
verifies tokenizer identity/counts, encodes complete inventory, and publishes a
closed temporary SQLite file only after complete base and semantic reopen checks.
Failure preserves input and the previous output. An empty inventory is valid.

Semantic format v1 keeps base `user_version=1`, documents/chunks and provenance.
It adds `embedding_metadata(singleton, metadata)` and
`chunk_embeddings(chunk_id PRIMARY KEY REFERENCES chunks, vector BLOB)`.
Metadata JSON includes semantic format version, model/revision, assets/tokenizer
fingerprints, dimension, dtype, normalization, input version and package versions.
Each vector contains exactly 1536 bytes encoded as 384 little-endian float32 values.
Readers check schema/keys, complete ID coverage, finite values and unit norms.
Base StorageReader can independently read the same file without model dependencies.

On identity mismatch, rebuild a separate output with compatible assets. There is
no in-place upgrade. Rollback restores the previous compatible semantic file and
configuration; the original storage pipeline needs no migration.

## Query API and CLI

```python
from pathlib import Path
from app.config import EmbeddingSettings
from app.embeddings import LocalEncoder
from app.retrieval import SemanticIndex

encoder = LocalEncoder(EmbeddingSettings(Path("/data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3")))
index = SemanticIndex(Path("/data/semantic.db"), encoder)
results = index.search("Как настроить сервер?", k=10)
```

Reuse an index/encoder for repeated questions. Search receives only the supplied
question, stores no history and performs no rewriting. It returns a tuple of typed
`SearchResult(rank, score, chunk)` objects. `to_dict()` includes source identity,
URL/title/headings, source ranges, source/generated segments and continuation
metadata. Cite source slices using ranges; generated segments are not source quotes.

```sh
python -m app.retrieval query --index /data/semantic.db --question 'Как настроить сервер?' --top-k 10
docker compose run --rm --no-deps app python -m app.retrieval query --index /data/semantic.db --question 'Как настроить сервер?'
```

`--model-path` overrides the configured path. Default k is 10; k must be a positive
integer. Ranking uses exact cosine similarity, score descending and chunk ID
ascending for ties. k above inventory returns all chunks; empty inventory returns
no results after query validation. There is no answerability threshold: scores
are not probabilities, and this API neither generates answers nor refuses them.
Snapshots open read-only; model mismatch requires a rebuild, with no fallback.

## Frozen evaluation protocol v1

```sh
python -m app.retrieval evaluate --questions /data/eval/questions.yaml --manifest /data/eval/manifest.json --snapshot /data/eval/1/wiki-documents.json --index /data/semantic-live.db --fixtures /data/eval/fixtures/wiki-documents.json --synthetic-index /data/semantic-synthetic.db
docker compose run --rm --no-deps app python -m app.retrieval evaluate --questions /data/eval/questions.yaml --manifest /data/eval/manifest.json --snapshot /data/eval/1/wiki-documents.json --index /data/semantic-live.db --fixtures /data/eval/fixtures/wiki-documents.json --synthetic-index /data/semantic-synthetic.db
```

Provision the unchanged repository `eval/questions.yaml`, `eval/manifest.json`,
and `eval/fixtures/wiki-documents.json` under `/data/eval` before using these
Compose examples. Build separate live/synthetic storage and semantic files from
their frozen reference snapshots using the existing chunking/storage commands
and default chunk settings: target 350, maximum 450, overlap 50, input limit 512.
Evaluation checks corpus integrity, exact source inventories/content/metadata,
and fixed chunk settings. It refuses mismatching corpus/index pairs.

Evidence uses page identity and required `spans` with start/end character offsets
into the unchanged source Markdown. A hit requires complete coverage of every
required span by the union of source ranges in the top five chunks. A matching
page, a partial composite/conflict hit or generated header is insufficient.
`partial_answer` and `report_conflict` cases with evidence enter the denominator;
refuse and clarify cases appear separately. No answer generation is performed.

Only this adapter composes `previous_question + "\n" + current_question` for
follow-up cases, without previous answers. The same 512-token query limit applies;
overflow fails without shortening. Follow-up metrics have their own counts,
hits/misses and Hit@5 inside each live/synthetic × tuning/holdout group. Ordinary
single-question denominators exclude them. Empty denominators have a null rate.

The report records corpus/reference/index fingerprints, settings, model/runtime
identity, stable case IDs/rankings, per-case latency and process peak memory.
First-query latency includes lazy model load; process peak memory includes that
load and native allocations. Inputs are hashed before and after evaluation.

### Measured development baseline, 2026-10-09

Full evidence is in [semantic-retrieval-baseline.json](semantic-retrieval-baseline.json).
Environment: Windows 11 build 26200, Python 3.12.7, Intel64 Family 6 Model 154
Stepping 4; four CPU threads and batch size 16. Socket connections were prohibited
for build and evaluation. Live inventory: 24 documents/910 chunks; synthetic:
1 document/1 chunk. The two runs used identical files and settings, with identical
rankings, scores and counts. Corpus/reference/index hashes were unchanged.

| Source / split | Single-question Hit@5 | Follow-up Hit@5 |
| --- | --- | --- |
| Live tuning | 5/9 (55.56%) | 0/1 (0%) |
| Live holdout | 0/3 (0%) | 0/1 (0%) |
| Synthetic tuning | No cases | No cases |
| Synthetic holdout | 1/1 (100%) | No cases |

Live tuning single-question misses: q02, q03, q07, q11; holdout misses: q04, q08,
q18. Follow-up misses: q09 (tuning), q10 (holdout). Refuse: q14/q15/q17 (tuning),
q16 (holdout); clarify: q13 (tuning). Holdout was measured with the fixed protocol
and was not used to tune parameters or corpus.

Query totals including first lazy load: 5.330 s and 5.225 s. Process peak working
sets: 1,015,058,432 and 1,017,507,840 bytes (about 968–971 MiB). Initial live
chunking/storage/semantic build took 41.219 s; synthetic preparation in its own
process took 5.474 s. These are development-machine measurements. The pure
semantic baseline does not achieve the final MVP 90% target on this corpus;
that target is not a semantic-stage acceptance condition.

## Target-server acceptance remains open

Task 5.2 has not been measured on the target i5-14400/15 GiB/Linux server. No
server access was supplied. Development results cannot establish Wiki.js
responsiveness, swap behavior or server resource usage.

On that server, preinstall dependencies/assets, prepare the frozen inputs and
build the app image. Run build in a separate disposable container with
`--network none`, mounting only `/data` and using the already-built image. Close
that process; run query and evaluate in new containers with `--network none`.
For example, after identifying the local image as `chago-app`:

```sh
docker run --rm --network none -v "$PWD/data:/data" chago-app python -m app.embeddings build --input /data/storage.db --output /data/semantic.db
docker run --rm --network none -v "$PWD/data:/data:ro" chago-app python -m app.retrieval query --index /data/semantic.db --question 'Как настроить сервер?'
```

Use the evaluate options above in another offline container. Record CPU/OS/image
identity, timings, peak memory, `free -b`, `vmstat` swap activity and ordinary
Wiki.js page latency before/during inference. Preserve input/output hashes and
verify a controlled corrupt-assets failure leaves the previous output unchanged.
Do not stop Wiki.js or clear the host page cache for these measurements.

## Verification record

On 2026-10-09, a clean Windows Python 3.12 environment installed the pinned runtime.
`pip check` reported no broken requirements. Import smoke verified torch `2.7.1+cpu`,
`torch.version.cuda is None`, no available CUDA, Sentence Transformers `5.1.2`,
NumPy `2.2.6`, and tokenizers `0.22.2`. Before heavy-library imports, HTTP health and
storage imports worked without loading any model/tokenizer library or assets.

Targeted embedding configuration, existing HTTP configuration and health tests:
36 passed. Configuration typing passed using the project's `app/typings` stubs.
These checks do not establish inference quality or target-server performance.

Final acceptance on the development machine: targeted semantic/config/evaluation
suite 198 passed; subsequent focused CLI/storage checks 54 passed. Full app suite:
564 passed, 6 skipped, one existing Starlette TestClient/httpx deprecation warning.
All real E5 tests executed; there were no model-asset skips. The six skips were
two Windows symlink-privilege tests (`test_chunking_cli.py:90`,
`test_index_storage_cli.py:51`) and four ingestion POSIX-permission cases
(`test_ingestion.py:61`). Full app typing passed for all 15 modules with the
existing `app/typings` stubs and no suppressions. OpenSpec strict validation passed.
Base semantic-file reading and actual HTTP health also passed in a fresh process
with numpy/torch/Sentence Transformers/Transformers/tokenizers imports blocked.
