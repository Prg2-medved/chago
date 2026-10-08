# SQLite storage snapshots

This offline stage saves chunking output in a derived SQLite file. It does not
create embeddings, run E5 inference, provide retrieval or FTS5, orchestrate
reindexing, or load a database during FastAPI startup. Tokenizer identity describes
the producer of the chunks; it is not evidence that embeddings exist.

## Input contract

Input is the existing chunking JSON `schema_version: 1`: source origin,
`algorithm_version`, tokenizer identity, settings, documents and chunks.
`app.index_storage.parse_output(payload)` returns a typed `StorageSnapshot`;
`load_output(Path(...))` reads and validates JSON. No tokenizer module or assets,
Wiki.js credentials, LLM or network access is needed.

Validation rejects bools in integer fields, unknown input schema versions,
invalid origins, document IDs and duplicate locale/path identities, mismatched
source URLs, timestamps and SHA-256 Markdown hashes. Chunks must reference a
document, match its duplicated metadata, have unique SHA-256-shaped IDs and
contiguous zero-based ordinals per document. Source segments have valid roles and
nonempty ranges in Unicode code points, not UTF-8 bytes; generated segments have
`table_header`, `fence` or `separator` reasons. Ordered `source_ranges` must equal
the source segments and `search_text` must equal the concatenated source slices
and generated text. Heading paths and JSON structure are preserved.

Settings satisfy `0 <= overlap < target <= maximum <= 450` and
`1 <= input_limit <= 512`. Token counts are nonnegative and bounded by those
settings; input counts cannot be below body counts. Storage does not recalculate
E5 counts or verify local tokenizer assets. Tokenizer metadata requires model,
revision, package/version, nonempty asset SHA-256 mapping and its matching
SHA-256 fingerprint (sorted compact JSON). Algorithm identity is retained rather
than interpreted as the storage schema version. Empty inventories and documents
without chunks are supported.

## Schema and read API

Schema v1 uses rollback journaling, without WAL sidecars, and
`PRAGMA user_version=1`.

| Table | Contents and constraints |
| --- | --- |
| `snapshot_metadata` | Singleton source, input schema/algorithm versions, tokenizer and settings JSON |
| `documents` | All Document fields, exact Markdown; PK `(source, page_id)`, UNIQUE `(source, locale, path)` |
| `chunks` | PK `chunk_id`, FK `(source, page_id)`, UNIQUE `(source, page_id, ordinal)`, text/counts and nested JSON |

Heading paths, segments, source ranges and structure use canonical JSON TEXT.
Scalar fields and Markdown round-trip exactly, including Unicode and CRLF;
nested JSON round-trips semantically, preserving array order. Chunk document
metadata is restored from documents so the two copies cannot diverge. One file
contains one complete source inventory; source is part of document identity.

```python
from pathlib import Path
from app.index_storage import StorageReader, load_output, write_snapshot

write_snapshot(Path("../data/storage-snapshot.db"), load_output(Path("../data/chunks.json")))
with StorageReader(Path("../data/storage-snapshot.db")) as reader:
    metadata = reader.snapshot
    documents = reader.documents
    chunks = reader.chunks
    chunk = reader.get_chunk(chunks[0].chunk_id) if chunks else None
    missing = reader.get_chunk("unknown")  # None
```

Reader opens a read-only URI without creating missing files and checks version,
required columns/keys/foreign keys, integrity, metadata and the full input
contract. It materializes typed records in memory. Documents are ordered by
source/page_id; chunks by source/page_id/ordinal/chunk_id. Connections support
explicit `close()` and context management. Unsupported schemas are rejected:
recreate the derived file from JSON instead of migrating it automatically.

`write_snapshot` creates a neighboring temporary file, writes the complete
inventory in one transaction, closes it, reopens read-only for validation and
compares the entire logical snapshot before `os.replace`. A failure preserves
the previous output and cleans temporary files. A successful import replaces
all inventory, including removal of stale pages and chunks. Repeated imports
produce equal logical records; byte-identical SQLite files are not promised.
Use parsed snapshots as writer input. The command is for offline administration
without concurrent writers or open consumers. Close readers before replacement,
especially on Windows.

## Administrative commands

From `app/`, using the project's Python environment:

```powershell
../.venv/Scripts/python.exe -m app.index_storage --input ../data/chunks.json --output ../data/storage-snapshot.db
```

From the repository root, using the existing `./data:/data` mount:

```sh
docker compose run --rm --no-deps app python -m app.index_storage --input /data/chunks.json --output /data/storage-snapshot.db
```

The app image must include the new module. Compose requires its existing external
`wiki_default` network even though this command does not access Wiki.js or LLM.
Both paths are explicit and the output directory must exist. CLI rejects output
aliases of input, including symlinks and hardlinks, before writing. Success emits
JSON with `documents`, `chunks` and `storage_version`; failures return code 1 with
a safe `storage:` category, never source content or credentials. Keep the JSON
input for reproducible rebuilds. This file is a storage snapshot, not the final
retrieval index.

## Verification

From `app/`:

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_index_storage.py tests/test_index_storage_cli.py -q
../.venv/Scripts/python.exe -m pytest tests/test_health.py tests/test_chunking_cli.py -q
../.venv/Scripts/python.exe -m mypy app/index_storage.py --follow-imports=silent
```

The real chunking round-trip test uses local E5 assets when installed and skips
explicitly when absent; it builds synthetic Markdown without changing the frozen
corpus. CLI tests run without Wiki/LLM environment settings. A symlink test may
skip on Windows when the account lacks symlink privileges.

Workspace verification: storage/CLI tests passed (103 passed, 1 symlink skip),
health/chunking CLI checks passed (9 passed, 1 symlink skip), and mypy reported
no issues. The local CLI example was exercised with isolated files under
`tmp/storage-acceptance/`, reporting one document, one chunk and storage version 1.
The real E5 chunking round-trip passed with the installed assets. Health tests
emit the existing Starlette/httpx deprecation warning.

Server acceptance was reported successful by the user on 2026-10-08 on Linux /
Docker Compose. The real Compose CLI returned exit code 0 with `documents=1`,
`chunks=1` and `storage_version=1`; the SQLite snapshot was created through the
existing `/data` mount. `PRAGMA integrity_check` returned `ok` and
`PRAGMA foreign_key_check` returned `[]`. Both hardlink and symlink input aliases
were rejected with exit code 1, preserving the original JSON. This completes
container acceptance independently of Docker availability in the local workspace.
