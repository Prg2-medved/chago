# Lexical and hybrid retrieval

## Technical completion and quality handoff, 2026-10-09

The project owner separated technical completion from retrieval quality
acceptance. Implementation, regression checks, reproducible comparison and
actual server acceptance are complete. Measured hybrid Hit@5 remains **6/12
(50%)**; the mandatory MVP **>=90%** target has **not** been achieved.
The original task 5.5 criterion remained unmet. Its revised completion criterion
records the failure, [six-case diagnostics](lexical-and-hybrid-retrieval-diagnostics.md)
and transfer of quality work to the separate `retrieval-quality-improvement`
stage in [ROADMAP](../ROADMAP.md), with the target retained in
[SPEC](../SPEC.md) sections 12.5, 27 and stage 4a. Technical task completion
and archiving do not mean quality acceptance. Future functionality needs a new
OpenSpec proposal/design; the frozen corpus, expectations, reports, retrieval
settings and previous baselines remain unchanged. Historical task-status
statements in the measurement records below describe the state before this decision.

OpenSpec confirmed `all_done` (25/25 current task criteria). The technical
change is [archived](../openspec/changes/archive/2026-10-09-lexical-and-hybrid-retrieval/tasks.md)
and its lexical/hybrid/semantic delta specs are synced to main specs. The next
step is a separate proposal from ROADMAP stage 9, not implementation in this archive.

## Storage and offline build

The FTS extension preserves base storage v1 and semantic format v1. Lexical
format, input format, query policy and literal policy are version 1. A
content-bearing FTS5 table indexes title, `" > ".join(heading_path)` and
search_text with standard unicode61, full detail and equal BM25 weights.
Metadata records counts, SQLite version and compile options; runtime checks
supported policies/options rather than requiring identical build-host options.

From `app/`, using the existing Python environment:

```sh
python -m app.lexical_storage build --input ../data/semantic-smoke.db --output ../data/hybrid-smoke.db --model-path ../data/models
```

The model path protects assets from accidental overwrite; build never loads
them or performs inference. Input is opened read-only and backed up to a
temporary file beside output. Base, semantic and lexical checks, including
raw vector byte equality, finish before closed-file publication. Rebuilding
replaces all lexical rows. Empty snapshots are supported. Input/output aliases
and files within, or aliased to, assets are rejected.

Compose equivalent (existing `/data` mount):

```sh
docker compose run --rm --no-deps app python -m app.lexical_storage build --input /data/semantic-live.db --output /data/hybrid-live.db
```

FTS5 is required from the installed SQLite runtime. `lexical_capability` means
the runtime cannot create an FTS5 table; use a preinstalled FTS5-capable Python
runtime, then rebuild. Query never downloads an extension or repairs a file.
`LexicalReader` opens an existing file read-only, verifies exact content/IDs
and runs SQLite FTS integrity-check on a disposable in-memory backup. Stale
content is rejected even when its postings are internally consistent.

Rollback: keep the original semantic snapshots, invoke the existing
`app.retrieval` commands with them, and retain the previous output if any build
fails. No in-place migration or HTTP startup change is required.

## Lexical API and queries

```sh
python -m app.lexical_retrieval query --index ../data/hybrid-smoke.db --question '14 дней' --top-k 10
docker compose run --rm --no-deps app python -m app.lexical_retrieval query --index /data/hybrid-live.db --question 'Как настроить route-plan?' --top-k 10
```

Use `with LexicalIndex(path) as index: results = index.search(question, 10)`.
The retained connection is read-only and closed on context exit. Lexical query
needs no NumPy, torch, tokenizer package or model assets. Questions are ordinary
text: an in-memory unicode61/fts5vocab probe extracts sorted unique terms;
escaped quoted terms are joined with OR and bound to MATCH. User operators and
column filters never become query syntax. BM25 is ordered ascending, ties by
chunk ID. Scores describe ranking, not answer probability.

Literal policy v1 extracts paired single-backtick fragments, IPv4/IPv6,
POSIX/Windows paths and names with hyphens without changing their spelling.
Quoted commands remain whole; unquoted overlapping candidates retain the
longest value. Use backticks for ambiguous paths/commands containing spaces.
Unclosed backticks are punctuation. Technical token boundaries exclude parts
of longer identifiers, IPs and paths. All chunks participate before top-k:
literal matches first, then more distinct literals, then available/lower BM25,
then chunk ID. Literal-only candidates have null BM25.

Evidence searches continuous source ranges of original Markdown; overlapping
or adjacent ranges merge, discontinuous ranges do not. Generated text supplies
no literal evidence. Offsets are original Python Unicode code points `[start,
end)`, preserving emoji/CRLF and checking neighbors in the complete document,
even beyond chunk boundaries. JSON retains source/generated segments and
continuation metadata, omits full document Markdown and exposes literal
ranges for direct verification against the source. JSON escapes Unicode so
Windows console encodings can carry the complete result losslessly.

Development verification: documented smoke build and query were executed with
SQLite 3.45.3; the output reopened with heavy imports blocked and no assets.

## Hybrid API, settings and lifecycle

`HybridIndex(path, encoder, settings)` is a context manager. Both branches use
one validated base handle and read transaction, started before base checks.
Vectors are loaded through that handle; lexical SQL keeps it until close. A
new instance loads a new generation. On Windows an open reader can prevent
publication; the build then preserves the existing output. Always close the
index, including on errors. Any missing/corrupt/incompatible branch fails the
request. A successfully empty lexical branch contributes no RRF score. A valid
zero-chunk snapshot still performs ordinary semantic query encoding and budget
validation before returning `[]`.

Defaults are semantic candidates=10, lexical candidates=10, RRF constant=60,
final top-k=6. `RetrievalSettings` and `load_retrieval_settings` validate positive
integers, excluding bool. Environment settings `RETRIEVAL_SEMANTIC_CANDIDATES`,
`RETRIEVAL_LEXICAL_CANDIDATES`, `RETRIEVAL_RRF_CONSTANT`, `RETRIEVAL_TOP_K` have
matching Compose mappings; explicit CLI overrides take precedence. They do
not affect HTTP startup/health. Export environment settings for local Python;
it does not automatically load `.env`.

```sh
python -m app.hybrid_retrieval query --index ../data/hybrid-smoke.db --question '14 дней' --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --semantic-candidates 10 --lexical-candidates 10 --rrf-constant 60 --top-k 6
docker compose run --rm --no-deps app python -m app.hybrid_retrieval query --index /data/hybrid-live.db --question 'Как настроить сервер?' --top-k 6
```

RRF sums `1/(constant+rank)` from each contributing branch, without mixing raw
cosine/BM25 or applying another literal boost. Final ties use chunk ID. Each
chunk appears once; different chunks of the same page remain distinct. A limit
above union size returns the union with no additional branch requests. JSON
distinguishes RRF, cosine and BM25, retains branch ranks/nulls, literal evidence
and original provenance. Ordinary queries use only the supplied question.
Semantic/hybrid retain the E5 512-token limit with no truncation. Existing pure
semantic query remains available, with unchanged JSON/cosine and default k=10.

## Frozen comparison and acceptance

Run the same extended snapshots through all three modes. Provision repository
`eval/questions.yaml`, `eval/manifest.json` and `eval/fixtures/wiki-documents.json`
under `/data/eval` for Compose, keeping the frozen live reference under
`/data/eval/1/wiki-documents.json`. From `app/` on the development machine:

```sh
python -m app.hybrid_retrieval evaluate --questions ../eval/questions.yaml --manifest ../eval/manifest.json --snapshot ../data/eval/1/wiki-documents.json --index ../data/hybrid-live.db --fixtures ../eval/fixtures/wiki-documents.json --synthetic-index ../data/hybrid-synthetic.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --split tuning
docker compose run --rm --no-deps app python -m app.hybrid_retrieval evaluate --questions /data/eval/questions.yaml --manifest /data/eval/manifest.json --snapshot /data/eval/1/wiki-documents.json --index /data/hybrid-live.db --fixtures /data/eval/fixtures/wiki-documents.json --synthetic-index /data/hybrid-synthetic.db --split tuning
```

Use `--split tuning|holdout|all` (default all). Full corpus validation precedes
execution, but only the selected split runs queries. Tune only branch candidate
counts/RRF constant on tuning; record the selected settings before a new holdout
run. Do not tune again using new holdout misses. Holdout was already exposed in
the previous semantic baseline and this comparison is not blind evaluation.

Report schema v1 retains evidence protocol v1: evaluation explicitly calls
`search(question, 5)` and evidence coverage additionally slices `results[:5]`.
All mandatory original source spans must be covered together in that namespace.
Partial/composite coverage, generated text and page identity alone are misses;
the sixth result cannot satisfy Hit@5, even though hybrid query defaults to six.
Only the evaluation adapter joins follow-up as previous question + newline +
current question, without answers or shortening. Follow-up has separate metrics.
Refuse/clarify are outside answerable denominators, and synthetic never improves
live scores. Live single-question aggregate sums tuning/holdout hits and counts.
Empty denominator yields null.

Each mode runs in its own fresh subprocess, with offline Hub/Transformers flags.
Lexical worker imports no heavy embedding libraries. Initialization is measured
separately; the first query includes lazy model loading, and a second pass gives
warm per-query latency. Peak memory uses Windows PeakWorkingSetSize or Unix
ru_maxrss; processes retain ordinary OS caches. Reports merge only with matching
fingerprints, environment, policies, split and effective settings. Rankings,
scores and counts must repeat; timings/peak memory need not. Hashes before/after
cover corpus, references and both indexes. Old baselines/inputs stay unchanged.

Quality acceptance requires measured hybrid live single-question Hit@5 >=90%
on both splits together, with separate split/follow-up results. A lower score
leaves acceptance open and lists miss IDs; it does not authorize changing frozen
expectations, chunking, model, reranker or denominators.
This is an MVP quality criterion for the separate improvement stage, rather
than an archive blocker for the completed technical lexical/hybrid stage.

## Target Linux/Docker procedure

Preinstall pinned dependencies/assets and build the image before runtime. With
the existing image identified as `chago-app`, run separate disposable offline
containers and mount data read-only for queries/evaluation:

```sh
docker run --rm --network none -v "$PWD/data:/data" chago-app python -m app.lexical_storage build --input /data/semantic-live.db --output /data/hybrid-live.db
docker run --rm --network none -v "$PWD/data:/data:ro" chago-app python -m app.lexical_retrieval query --index /data/hybrid-live.db --question 'route-plan'
docker run --rm --network none -v "$PWD/data:/data:ro" chago-app python -m app.hybrid_retrieval evaluate --questions /data/eval/questions.yaml --manifest /data/eval/manifest.json --snapshot /data/eval/1/wiki-documents.json --index /data/hybrid-live.db --fixtures /data/eval/fixtures/wiki-documents.json --synthetic-index /data/hybrid-synthetic.db --split all
```

Also build the synthetic extension before evaluation. Record SQLite version/
compile options and FTS capability, base/semantic reopen and raw vector hashes,
input SHA-256 preservation, controlled build failure preservation, process
latency/peak memory, image/CPU/OS identity, and Wiki.js responsiveness before and
during build/inference. Do not attribute development measurements to the server.
Server acceptance requires an actual server report.

The detailed [Linux/Docker acceptance procedure](lexical-and-hybrid-retrieval-server-acceptance.md)
targets `/home/prg2/chago-llm/chago`, separates image provisioning and repeated
offline checks, and records lossless checks, controlled failures, per-mode
measurements and Wiki.js impact without restarting existing containers. Task
5.4 is complete based on the operator's actual server report recorded below.

## Target Linux/Docker results, 2026-10-09

The operator supplied actual acceptance results for Git `7c8ee21`, image
`sha256:c7182f9156933781c2bcdef63cfa5a34141eac8fe773ff682df9e2d17bdf2187`,
SQLite 3.46.1 with FTS5 unicode61, PyTorch 2.7.1+cpu and manifest-checked E5.
Runtime used `--network none`, 4 CPU and a 5 GiB memory limit. The
[server report and criterion mapping](lexical-and-hybrid-retrieval-server-acceptance.md#фактический-серверный-отчёт-2026-10-09)
record the result directory, lossless validation, failure preservation,
snapshot SHA-256 preservation and identical rankings/scores/counts in two runs.
The primary server files were not read during this documentation update.

| Mode | Initialization, s | Peak RSS, bytes | Live single-question Hit@5 |
| --- | --- | --- | --- |
| Semantic | 0.754 | 1123176448 | 5/12 (41.67%) |
| Lexical | 0.052 | 51920896 | 3/12 (25%) |
| Hybrid | 0.667 | 1123598336 | 6/12 (50%) |

Wiki.js baseline: 20 requests, 0 errors, mean 19.57 ms, max 32.91 ms.
During evaluation: 11 requests, 0 errors, mean 12.07 ms, max 25.50 ms.
Swap max si/so: 16/0 KiB/s; available RAM after the test: 7.8 GiB; free disk:
16 GiB. Working containers were unchanged (`container_diff_exit_code=0`) and
were not restarted. These observations describe the measured samples.

**Historical state before the owner's completion decision: task 5.4 complete;
original task 5.5 open.** Hybrid quality is 50%, below
the 90% target; miss IDs are q02, q03, q04, q07, q08, q18. The server summary
does not provide build timings, cold/warm query latency, Wiki.js p95 or separate
split/follow-up metrics; initialization is not query latency. Further limits
of the supplied data are listed in the server report. Development values below
remain separate. The change was not archived at the time of that server record.

## Development measurements, 2026-10-09

The measured [comparison report](lexical-and-hybrid-retrieval-baseline.json)
contains fingerprints, environment/SQLite identity, all case rankings/scores,
split/follow-up metrics, transitions, per-query cold/warm timings, per-process
peak memory, build audit, tuning grid and repeat verification. These are Windows
Python 3.12 development results, separate from the Linux/Docker results above.

Defaults 10/10/60/6 gave tuning single-question semantic 5/9, lexical 3/9,
hybrid 4/9. Tuning tried semantic candidates 5/10/20/40, lexical candidates
1/3/5/10/20 and RRF constants 1/10/60. Only live tuning answerable cases were
executed; selection maximized single-question hits, then follow-up hits, then
closeness to defaults. Settings 10/1/60/6 were written to a separate settings
file before the new holdout. API defaults remain 10/10/60/6. New holdout misses
were not used for another tuning cycle.

| Mode | Live tuning single | Live holdout single | Live aggregate | Follow-up tuning / holdout |
| --- | --- | --- | --- | --- |
| Semantic | 5/9 | 0/3 | 5/12 (41.67%) | 0/1 / 0/1 |
| Lexical | 3/9 | 0/3 | 3/12 (25%) | 0/1 / 0/1 |
| Hybrid, selected settings | 6/9 | 0/3 | 6/12 (50%) | 0/1 / 0/1 |

Synthetic holdout single-question is 1/1 in each mode; synthetic tuning has
no cases. Synthetic, follow-up, refuse and clarify remain outside the live
single-question aggregate. Hybrid changes q11 from semantic miss to hit without
regressing semantic hits. Hybrid misses: q02, q03, q04, q07, q08, q18; follow-up
misses q09/q10. **Quality target >=90% is not achieved; retrieval quality
acceptance has not passed. The original task 5.5 was open at measurement time.** Frozen corpus,
reference, chunking, model and old baseline remain unchanged.

| Mode | Initialization, s | First query, s | Warm mean/query, s | Process peak memory, bytes |
| --- | --- | --- | --- | --- |
| Semantic | 1.216944 | 8.894138 | 0.028659 | 1,019,236,352 |
| Lexical | 0.079175 | 0.001757 | 0.002531 | 54,808,576 |
| Hybrid | 1.012410 | 8.958331 | 0.032170 | 1,022,771,200 |

Each mode used its own process. First query includes lazy E5 loading for
semantic/hybrid; warm timings are a second pass over the same cases. Windows
peak working set includes index validation, including disposable FTS backup.
No host page-cache clearing was performed. Lexical loaded no heavy embedding
libraries. Repeating the full fixed comparison preserved rankings/scores/counts
and fingerprints; timing and memory differed as expected.

Audited extension build took 0.358303 s for live (24 documents/910 chunks) and
0.032737 s for synthetic (1/1), without inference. Base snapshots/provenance,
semantic metadata and sorted raw embedding bytes matched after reopen. SHA-256
of original semantic snapshots, corpus/reference, model manifest and previous
baseline stayed unchanged. The full report contains their hashes and per-index
raw-vector hashes. Query and validation did not modify extended DB files.

## Verification record

Targeted suites passed before the full suite: original storage/semantic/query
151 tests before and after the shared reader change; lexical storage/CLI 31
passed with one symlink skip; lexical query/CLI 35 passed; hybrid/settings/HTTP
66 passed; original evaluation 91 before and after; comparison/evaluation/hybrid
CLI 23 passed. The full app suite passed **688 tests, 7 platform skips**, with
one existing Starlette TestClient/httpx deprecation warning. Skips are three
Windows symlink-privilege checks and four POSIX ingestion permission cases.
Installed real E5 assets were used, with no model-asset skips.

Typing passed for all nine affected modules using existing `app/typings` stubs,
without suppressions or added dependencies. Fresh-process base storage, actual
HTTP health and lexical query passed with heavy imports blocked. Documented
smoke build/query and real hybrid query ran; original semantic query returned
its default ten results. OpenSpec strict validation passed. The separate server
guide's 13 Bash blocks passed `bash -n`, and seven embedded Python snippets
compiled; this syntax check is not a server execution report.

After the full suite, a final SQLite initialization diagnostic check and related
lexical/hybrid/comparison suites passed 93 tests with one Windows symlink skip;
typing again passed all nine modules. Initialization failures close their
handles and expose only the safe `lexical_query` category.
