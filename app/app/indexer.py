"""Full offline rebuild with one final SQLite publication (app must be stopped)."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from time import monotonic
from typing import Any

from app import chunking, ingestion, index_storage, lexical_storage, semantic_storage
from app.config import load_embedding_settings, load_index_path, load_ingestion_settings
from app.embeddings import LocalEncoder
from app.index_state import ActiveIndex
from app.reindex_metadata import ReindexMetadata, write_metadata


class ReindexError(ValueError):
    """Only safe categories may cross the CLI boundary."""


@contextmanager
def builder_lock(path: Path) -> Iterator[None]:
    # Linux target; isolate platform imports so readers work on Windows.
    if sys.platform != "linux":
        raise ReindexError("linux_required")
    import fcntl

    with path.with_name(path.name + ".builder.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReindexError("builder_busy") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def protect_output(path: Path, assets: Path) -> Path:
    try:
        output, model = path.resolve(), assets.resolve()
        if output.is_relative_to(model) or not output.parent.is_dir() or output.is_dir():
            raise ReindexError("output_path")
        if output.exists():
            for asset in model.rglob("*"):
                if asset.is_file() and output.samefile(asset):
                    raise ReindexError("output_path")
        return output
    except OSError:
        raise ReindexError("output_path") from None


def require_standalone(path: Path) -> None:
    """Inspect headers only: opening active in SQLite could recover its journal."""
    if any(os.path.lexists(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        raise ReindexError("sqlite_sidecars")
    if path.exists():
        with path.open("rb") as handle:
            header = handle.read(100)
        if len(header) != 100 or header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
            raise ReindexError("sqlite_journal_format")


def normalize_candidate(path: Path) -> None:
    connection = sqlite3.connect(path, timeout=0)
    try:
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is None or checkpoint[0] != 0 or checkpoint[1] != checkpoint[2]:
            raise ReindexError("candidate_checkpoint")
        if connection.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
            raise ReindexError("candidate_journal_mode")
        connection.commit()
    finally:
        connection.close()
    require_standalone(path)


def rebuild() -> dict[str, Any]:
    started = monotonic()
    settings = load_embedding_settings()
    output = protect_output(load_index_path(), settings.model_path)
    source_settings = load_ingestion_settings()
    with builder_lock(output):
        require_standalone(output)
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.reindex-", dir=output.parent))
        published = False
        report: dict[str, Any] = {}
        try:
            source, base, semantic, candidate = (staging / name for name in
                                                ("source.json", "base.sqlite3", "semantic.sqlite3", "candidate.sqlite3"))
            ingestion.ingest(source_settings, source)
            encoder = LocalEncoder(settings)
            snapshot = index_storage.parse_output(chunking.build_output(
                chunking.load_snapshot(source), encoder.tokenizer, chunking.ChunkSettings()))
            index_storage.write_snapshot(base, snapshot)
            embedding_started = monotonic()
            semantic_storage.build(base, semantic, encoder)
            embedding_seconds = monotonic() - embedding_started
            lexical_storage.build(semantic, candidate, settings.model_path)
            metadata = ReindexMetadata(1, datetime.now(timezone.utc).isoformat(),
                                       len(snapshot.documents), len(snapshot.chunks))
            connection = sqlite3.connect(candidate)
            try:
                with connection:
                    write_metadata(connection, metadata, snapshot)
            finally:
                connection.close()
            normalize_candidate(candidate)
            with ActiveIndex(candidate) as ready:
                if ready.snapshot != snapshot or ready.metadata != metadata:
                    raise ReindexError("candidate_generation")
            require_standalone(candidate)
            require_standalone(output)
            report = {**asdict(metadata), "published": True, "embedding_seconds": embedding_seconds,
                      "indexing_seconds": monotonic() - started}
            os.replace(candidate, output)
            published = True
        finally:
            try:
                shutil.rmtree(staging)
            except Exception:
                if not published:
                    raise ReindexError("staging_cleanup") from None
                report["cleanup_warning"] = True
        return report


def main() -> int:
    try:
        print(json.dumps({"event": "reindex_start", "started_at": datetime.now(timezone.utc).isoformat()}), flush=True)
        report = rebuild()
    except Exception as error:
        # Exceptions can contain DB credentials, Markdown, paths or inference inputs.
        category = "build_failed"
        if isinstance(error, ReindexError) and str(error) in {
            "linux_required", "builder_busy", "output_path", "sqlite_sidecars", "sqlite_journal_format",
            "candidate_checkpoint", "candidate_journal_mode", "candidate_generation", "staging_cleanup",
        }:
            category = str(error)
        print(f"reindex: {category}; publication not completed", file=sys.stderr)
        return 1
    try:
        print(json.dumps({"event": "reindex_end", **report}, allow_nan=False), flush=True)
    except Exception:
        # Publication already succeeded. Never claim old state was retained.
        try:
            print("reindex: published; report_failed", file=sys.stderr)
        except OSError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
