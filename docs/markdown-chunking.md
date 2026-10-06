# Offline Markdown chunking

`app.chunking` converts ingestion snapshot schema_version 1 into a separate
versioned chunks JSON. It reads Markdown offline and does not call Wiki.js,
LLM, embedding inference or retrieval. Input documents and corpus files are
never rewritten. Derived files should stay in ignored `data/`.

## Tokenizer installation and identity

Model: `intfloat/multilingual-e5-small`.
Verified immutable revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
Installation resolved this commit from the [official model API](https://huggingface.co/api/models/intfloat/multilingual-e5-small)
and downloaded only the following files using HTTPS URLs under
[`resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/`](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3).
No model weights or SentencePiece runtime are needed.

| File | SHA-256 |
| --- | --- |
| tokenizer.json | `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39` |
| tokenizer_config.json | `a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b` |
| special_tokens_map.json | `d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7` |

The adapter verifies every byte hash against these reviewed constants before
loading. It accepts only this revision, disables padding/truncation, and uses
the original E5 special-token postprocessor. It loads the tokenizer library
only when the CLI constructs the adapter; HTTP startup does not load assets.
There is no runtime network fallback. Missing/corrupt assets cause
`tokenizer_assets`; other revisions, including `main`, branches/tags and
unverified commit IDs, are rejected.

Pinned runtime package: `tokenizers==0.22.2`. `mypy==1.19.1` is dev tooling only.
Assets fingerprint:
`573b6457b17946a70015f085b8b467715631438ac1a72ba8c4e2784813848850`.
It is SHA-256 of UTF-8 JSON mapping filenames to SHA-256, sorted keys,
compact separators `(',', ':')`. Output also records individual hashes and
the installed package version, which must equal the pin.

From repository root, install in PowerShell:

```powershell
.venv/Scripts/python.exe -m pip install -r app/requirements-dev.txt
$assetRevision = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
$assetDirectory = Join-Path 'data/tokenizers' $assetRevision
New-Item -ItemType Directory -Force -Path $assetDirectory | Out-Null
foreach ($assetName in @('tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json')) {
    Invoke-WebRequest -UseBasicParsing "https://huggingface.co/intfloat/multilingual-e5-small/resolve/$assetRevision/$assetName" -OutFile (Join-Path $assetDirectory $assetName)
}
Get-ChildItem -LiteralPath $assetDirectory | Get-FileHash -Algorithm SHA256
```

Compare hashes with the table. Installation is the only network operation;
processing uses preinstalled local files. The future embedding stage must use
a compatible tokenizer from the same model ID and immutable revision. It must
check saved identity/fingerprint/package compatibility before consuming chunks.
A mismatch requires explicit reconciliation and re-chunking, never ignoring
the saved token budget.

## Output and budgets

Top-level fields: `schema_version=1`, `algorithm_version=markdown-chunking-1`,
`source`, `tokenizer`, `settings`, original `documents`, and `chunks`.
Documents preserve every ingestion field without normalization, including
Markdown, timestamps, URLs and hashes. Empty documents produce zero chunks.

Each chunk contains `chunk_id`, `source`, all document metadata except Markdown,
`heading_path`, zero-based `ordinal`, `segments`, `source_ranges`, `search_text`,
`body_tokens`, `input_tokens`, and `structure`. Source ranges are half-open
Unicode code-point offsets, never UTF-8 byte offsets. A source segment contains
`kind=source`, `start`, `end`, and `role`; its text is always
`documents[page_id].markdown[start:end]`. A generated segment contains
`kind=generated`, `text`, and `reason` (`fence`, `table_header`, `separator`).
Generated text helps search and must not be quoted as original source.

The shared full-input formatter is exactly:

```text
passage: {title}
{heading path joined with ' > '}
{search_text}
```

An empty heading path leaves the middle line empty. Defaults are target 350,
maximum 450 body tokens, overlap 50, input_limit 512. Body counts exclude special
tokens; full passage counts include them. Generated text counts toward both
limits. Settings require integer `0 <= overlap < target <= maximum <= 450`
and `1 <= input_limit <= 512`. Every candidate and final full passage is counted
as a whole; independent token counts are never subtracted to infer a budget.
Metadata is not truncated. If the next source character with its required
context cannot fit, processing reports `budget` and publishes no output.

IDs hash canonical source origin, full document identity/content metadata,
settings, algorithm version, tokenizer identity, chunk ordinal, heading path,
segments and continuation metadata. Documents sort by page_id; chunks follow
source order and ordinal. JSON uses UTF-8, sorted keys, two-space indentation,
one final LF, and no timestamps. Different source origins prevent collisions
between live and synthetic namespaces; document input permutation does not
change output bytes.

## Supported structure and citation rules

The scanner preserves line endings and recognizes ATX/Setext headings,
backtick/tilde fenced blocks, info strings and unclosed fences. Headings inside
fences are code. Heading paths retain only existing levels; preamble has an
empty path. Every heading line remains in source coverage, including
heading-only documents. Nested/unsupported syntax, lists, indented code,
links/images and malformed tables use literal text fallback. No images are
downloaded or commands executed.

Prose is packed within one heading path, then split at source lines and,
for oversized lines, Unicode boundaries. The fallback accepts only verified
candidates and always advances. It does not assume monotone token counts.
Prose overlap is a source suffix up to 50 body tokens within the same block
and section. It shrinks or disappears when needed for new content. Code and
table slices are never duplicated as overlap. Structural chunks may be below
target; fitting code blocks remain intact even above target.

Code structure includes `block_id`, `part_index`, `continued_before/after`,
`language_fence`, `split_line` and `requires_complete_block`. All split code
parts conservatively require the original complete block to substantiate a
complete command, even when a part happens to contain complete lines. Missing
opening/closing fences are added only as generated search context. Citation
consumers must use source segments and may fall back to the preserved page URL.

Pipe tables detect escaped pipes and matching inline-code backtick runs. Valid
header/separator column counts must match. Fitting tables remain whole and
store `table_id` and row ranges. Oversized tables preserve header/separator once
as source, repeat them as generated context for subsequent row chunks, and
split oversized rows/cells by source lines/Unicode slices. Parts store
`table_id`, `row_index`, `part_index`, and continuation flags. Header-only chunks
are allowed. A header or header plus minimal row fragment that cannot fit
causes an explicit budget error. Table values never get rewritten.

For example, `# A` followed by `### B` yields heading path `['A', 'B']`;
`# comment` inside a Bash fence leaves the path unchanged. A long table row
keeps the same row_index across its parts, and repeated headers are generated.
These examples and CRLF/Unicode behavior are covered by structural tests.

## Running and recovery

From `app/` in PowerShell (commands executed on the fixture):

```powershell
../.venv/Scripts/python.exe -m app.chunking --input ../eval/fixtures/wiki-documents.json --output ../data/chunks-synthetic.json --tokenizer-path ../data/tokenizers/614241f622f53c4eeff9890bdc4f31cfecc418b3
../.venv/Scripts/python.exe -m app.chunking --input ../data/eval/1/wiki-documents.json --output ../data/chunks-live.json --tokenizer-path ../data/tokenizers/614241f622f53c4eeff9890bdc4f31cfecc418b3
```

Optional CLI-only flags are `--target`, `--maximum`, `--overlap`, `--input-limit`.
They do not enter HTTP settings validation. The destination parent must exist.
The report gives document/chunk counts, maxima and duration, never Markdown.
Output is first written to a temporary file beside the destination, then
atomically replaced. Errors return exit code 1 with a controlled category;
old output remains valid. Reinstall corrupt assets from the fixed commit,
correct invalid input/settings, or select a writable destination and rerun.
No partially produced artifact is published. Input/output aliases and
hardlinks, destinations inside tokenizer assets, and hardlinks to assets are
rejected. Atomic publication does not provide protection against concurrent
external mutation of filesystem links or source files.

From repository root, Compose uses the existing `./data:/data` mount:

```sh
docker compose build app
docker compose run --rm --no-deps app python -m app.chunking --input /data/eval/1/wiki-documents.json --output /data/chunks-live.json --tokenizer-path /data/tokenizers/614241f622f53c4eeff9890bdc4f31cfecc418b3
```

For the synthetic fixture, copy its unchanged bytes into `data/` for mounting:

```powershell
Copy-Item -LiteralPath eval/fixtures/wiki-documents.json -Destination data/chunking-synthetic-input.json
docker compose run --rm --no-deps app python -m app.chunking --input /data/chunking-synthetic-input.json --output /data/chunks-synthetic-compose.json --tokenizer-path /data/tokenizers/614241f622f53c4eeff9890bdc4f31cfecc418b3
```

No Compose configuration or permanent tokenizer mount was added. Normal
app-only startup does not require tokenizer files, Wiki.js or LLM. The existing
external `wiki_default` Docker network must already exist for Compose runs.
CLI alone requires tokenizer assets. Container acceptance remains pending until
actual results arrive from the target Linux server; the commands above have
not been claimed as executed there.

### Target Linux server checks for tasks 3.3/3.4

The target repository is `~/chago-llm/chago`. Transfer the current implementation,
runtime requirements and `docs/markdown-chunking-server-checks.sh` there before
running. Docker Engine, Compose v2, Bash, curl and the existing `wiki_default`
network are required. From the server shell:

```bash
cd ~/chago-llm/chago
bash docs/markdown-chunking-server-checks.sh
```

The script contains the exact commands and assertions. It installs only missing
tokenizer JSON assets from the immutable revision and verifies their SHA-256;
existing files with wrong hashes abort the run. It builds app under a unique
Compose project and uses the existing data mount. Fixture CLI runs twice with
the host UID/GID to keep output readable on Linux. It starts no Wiki.js or LLM
services, publishes no host ports, and changes no production containers.

Expected results:

| Check | Expected result |
| --- | --- |
| Asset installation | All three hashes report `OK`; no weights downloaded |
| Compose fixture CLI, twice | Exit 0; documents=1, chunks=1, max_body_tokens=45, max_input_tokens=67; duration may vary |
| Output verification | Byte-identical output; recorded model/revision/fingerprint/version match; real E5 recount gives 45/67; original source and URL preserved |
| Ordinary image entrypoint with empty `/data`, `--network none` | Container stays running; localhost `/health` returns HTTP 200 and `{"status":"ok"}` without tokenizer/Wiki.js/LLM |
| Compose CLI with missing assets | Exit 1; exact diagnostic `chunking: tokenizer_assets`; previous output/input/assets unchanged |
| Integrity | README/ROADMAP, Compose, frozen snapshots, manifest and questions hashes report `OK` |

The script retains logs and outputs in a new `data/chunking-compose-check.*`
directory, whose exact path is printed. Its exit trap removes only its own
health container and temporary Compose project resources; it retains the built
image and acceptance artifacts. On success the final line is
`PASS: all server checks complete; artifacts=...`.

Send that final line plus `cli-1.log`, `cli-2.log`,
`fixture-verification.log`, `health-verification.log`,
`missing-assets-verification.log`, and `image-id.txt` from the printed directory.
No full Markdown, `.env`, Compose environment dump or credentials are needed.
If a check fails, send its diagnostic and exit code instead. These commands
have been prepared, not executed on the server: tasks 3.3/3.4 remain unchecked
until actual server results are received.

## Verification evidence (2026-10-06)

Actual local E5 CLI was run twice independently on each frozen snapshot:

| Source | Documents | Chunks | Max body | Max full input | Duration, seconds |
| --- | ---: | ---: | ---: | ---: | --- |
| live | 24 | 910 | 447 | 467 | 1.531 / 1.516 |
| synthetic | 1 | 1 | 45 | 67 | 0.687 / 0.625 |

Each pair was byte-identical, including IDs and tokenizer identity.
Output SHA-256: live
`e35ed475cfd4dabdb62f43b18ead712763824315ff433bd95e0e2f48363581ab`,
synthetic `1423dfff20f580bf553ab55b0c62e98196aed083923643dbfead241482ece8d3`.
The real adapter verified individual asset hashes and recorded the fingerprint
and actual pinned package version shown above. Acceptance tests independently
recount every body/full passage, check source-segment assembly and union ranges,
all evidence spans and exact commands, and repeated output.

The frozen package contains 14 live tuning, 5 live holdout and 1 synthetic
holdout questions. Holdout is checked only for source preservation; parameters
are defaults, with no holdout tuning. This is not retrieval Hit@5.

Input integrity hashes before/after acceptance:

| File | SHA-256 |
| --- | --- |
| data/eval/1/wiki-documents.json | `63ad12fec898ef6c73c5c37a66d18e0d1327c91f1f79102dfa646cadd8c9f95f` |
| eval/fixtures/wiki-documents.json | `9fe75320ace79ef6ee707f189137c6fd9fd886341b65395c87393ea4f2d9cf1a` |
| eval/manifest.json | `9cea48706b1d4118c0a57cd88cce009f3f1ee6576c8b9c3d0dbd84bcec06c3a3` |
| eval/questions.yaml | `916c65e0e589a27e86b9afafdc91c6cad6c4b3ecbad8ab941f5af87bd1e14181` |

Manual safe citation selections use zero-based half-open ranges; abbreviated
chunk IDs below are prefixes of output SHA-256 IDs. Full Markdown and credentials
are omitted:

| Case | Page | Source range | Chunk ID prefix | Check |
| --- | ---: | --- | --- | --- |
| q02 Bash | 3 | [697,725) within [693,730) | ca1438980e1018cd | complete original fenced command, no generated text |
| q03 Bash | 43 | [3437,3473) within [3429,3478) | 3752320d65b2b293 | complete command and original URL preserved |
| q04 table values | 23 | [1265,1341) | 2b03b944e4992b6a | literal values preserved; malformed separator uses text fallback |
| q06 table rows | 40 | [899,987), [988,1076) | 9c2b3c01a9db3872 | exact rows preserved; mismatched header/separator counts use fallback |
| q08 long code | 19 | [549,1372), [1372,2272) | b16a926f583c3ecb / 9412e59cbdf94fdd | linked parts; requires_complete_block=true; generated fences excluded from quotes |
| q20 injection fixture | 1 (synthetic) | [59,152) | 8ded761e7297782b | inert source text preserved, never interpreted as instructions |

Validation commands from `app/`:

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_chunking.py tests/test_chunk_tokenizer.py tests/test_chunking_structure.py tests/test_chunking_cli.py tests/test_chunking_corpus.py -q -p no:cacheprovider
../.venv/Scripts/python.exe -m pytest tests/test_ingestion.py tests/test_evaluation.py tests/test_config.py tests/test_health.py -q -p no:cacheprovider
$env:MYPYPATH = 'typings'
../.venv/Scripts/python.exe -m mypy app/chunking.py app/chunk_tokenizer.py --follow-imports=silent
```

`typings/tokenizers.pyi` declares only the used API because the pinned package
does not ship a `py.typed` marker; no type errors are suppressed. Real tokenizer
tests skip if local assets are not installed; such skips never count as E5
acceptance. Windows symlink tests may skip when privileges are unavailable;
hardlink and resolved-path protection are still tested.

Results: 87 targeted tests passed, 1 skipped (Windows symlink privilege);
164 regression tests passed, 4 skipped (POSIX-only permission behavior).
Regression emitted the existing Starlette/httpx deprecation warning. Mypy
passed both changed modules. `openspec validate markdown-chunking --strict`
passed. Scoped review confirmed no embeddings/retrieval/SQLite/API, Compose,
HTTP settings, README/ROADMAP or ingestion/corpus changes. Container acceptance
for tasks 3.3/3.4 remains pending.
