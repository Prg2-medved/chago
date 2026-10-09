"""Versioned FTS5 extension, read-only validation and lossless offline build."""

import argparse
from contextlib import closing
from collections.abc import Sequence
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any, Never

from app.index_storage import StorageError, StorageReader, StorageSnapshot, _json


LEXICAL_VERSION = 1
QUERY_POLICY_VERSION = 1
LITERAL_POLICY_VERSION = 1
_FTS_SCHEMA = """CREATE VIRTUAL TABLE chunk_fts USING fts5(
    chunk_id UNINDEXED, title, heading_path, search_text,
    tokenize='unicode61', detail=full
)"""
_METADATA_SCHEMA = """CREATE TABLE lexical_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), metadata TEXT NOT NULL
)"""
_OPTIONS = {"tokenizer": "unicode61", "detail": "full", "content": "internal",
            "weights": [1.0, 1.0, 1.0]}


class LexicalStorageError(ValueError):
    """Safe category; backend exceptions never become diagnostics."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "lexical: arguments\n")


def probe_fts5() -> None:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text, tokenize='unicode61')")
    except sqlite3.Error:
        raise LexicalStorageError("lexical_capability") from None
    finally:
        if connection is not None:
            connection.close()


def lexical_metadata(snapshot: StorageSnapshot) -> dict[str, Any]:
    with closing(sqlite3.connect(":memory:")) as connection:
        options = sorted(row[0] for row in connection.execute("PRAGMA compile_options"))
    return {"format_version": LEXICAL_VERSION, "input_format_version": 1,
            "query_policy_version": QUERY_POLICY_VERSION, "literal_policy_version": LITERAL_POLICY_VERSION,
            "options": _OPTIONS, "documents": len(snapshot.documents), "chunks": len(snapshot.chunks),
            "sqlite_version": sqlite3.sqlite_version, "compile_options": options}


def _canonical_sql(sql: str) -> str:
    return re.sub(r"\s+", "", sql).lower()


def validate_lexical(base: StorageReader) -> dict[str, Any]:
    """Validate through the retained base handle; integrity writes use only a backup."""
    probe_fts5()
    connection = base._connection
    if connection is None:
        raise LexicalStorageError("lexical_closed")
    try:
        for name, schema in (("chunk_fts", _FTS_SCHEMA), ("lexical_metadata", _METADATA_SCHEMA)):
            row = connection.execute("SELECT sql FROM sqlite_master WHERE name=? AND type='table'", (name,)).fetchone()
            if row is None or _canonical_sql(row[0]) != _canonical_sql(schema):
                raise LexicalStorageError("lexical_schema")
        rows = connection.execute("SELECT singleton, metadata FROM lexical_metadata").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise LexicalStorageError("lexical_metadata")
        metadata = json.loads(rows[0][1])
        expected = lexical_metadata(base.snapshot)
        if not isinstance(metadata, dict) or set(metadata) != set(expected):
            raise LexicalStorageError("lexical_metadata")
        for key in ("format_version", "input_format_version", "query_policy_version", "literal_policy_version"):
            if type(metadata[key]) is not int or metadata[key] != expected[key]:
                raise LexicalStorageError("lexical_version")
        if _json(metadata["options"]) != _json(_OPTIONS):
            raise LexicalStorageError("lexical_options")
        for key in ("documents", "chunks"):
            if type(metadata[key]) is not int or metadata[key] != expected[key]:
                raise LexicalStorageError("lexical_coverage")
        if (not isinstance(metadata["sqlite_version"], str) or not metadata["sqlite_version"]
                or not isinstance(metadata["compile_options"], list)
                or any(not isinstance(item, str) for item in metadata["compile_options"])):
            raise LexicalStorageError("lexical_metadata")
        actual = [tuple(row) for row in connection.execute(
            "SELECT rowid, chunk_id, title, heading_path, search_text FROM chunk_fts ORDER BY rowid")]
        chunks = sorted(base.chunks, key=lambda chunk: chunk.chunk_id)
        if [row[1] for row in actual] != [chunk.chunk_id for chunk in chunks]:
            raise LexicalStorageError("lexical_coverage")
        expected_rows = [(i, chunk.chunk_id, chunk.document.title, " > ".join(chunk.heading_path), chunk.search_text)
                         for i, chunk in enumerate(chunks, 1)]
        if actual != expected_rows:
            raise LexicalStorageError("lexical_content")
        backup = sqlite3.connect(":memory:")
        try:
            connection.backup(backup)
            backup.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')")
        except sqlite3.Error:
            raise LexicalStorageError("lexical_postings") from None
        finally:
            backup.close()
        return metadata
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, (StorageError, LexicalStorageError)):
            raise
        raise LexicalStorageError("lexical_read") from None


class LexicalReader(StorageReader):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        try:
            self.metadata = validate_lexical(self)
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> "LexicalReader":
        return self


def _write_extension(path: Path, snapshot: StorageSnapshot, metadata: dict[str, Any]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS chunk_fts")
        connection.execute("DROP TABLE IF EXISTS lexical_metadata")
        connection.execute(_METADATA_SCHEMA)
        connection.execute(_FTS_SCHEMA)
        with connection:
            connection.execute("INSERT INTO lexical_metadata VALUES (1, ?)", (_json(metadata),))
            connection.executemany("INSERT INTO chunk_fts(rowid, chunk_id, title, heading_path, search_text) VALUES (?, ?, ?, ?, ?)",
                                   [(i, chunk.chunk_id, chunk.document.title, " > ".join(chunk.heading_path), chunk.search_text)
                                    for i, chunk in enumerate(sorted(snapshot.chunks, key=lambda chunk: chunk.chunk_id), 1)])
    finally:
        connection.close()


def _raw_vectors(path: Path) -> tuple[tuple[str, bytes], ...]:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return tuple(connection.execute("SELECT chunk_id, vector FROM chunk_embeddings ORDER BY chunk_id"))
    finally:
        connection.close()


def protect_paths(input_path: Path, output: Path, assets: Path) -> None:
    from app.semantic_storage import SemanticStorageError, protect_paths as semantic_protect
    try:
        semantic_protect(input_path, output, assets)
    except SemanticStorageError:
        raise LexicalStorageError("lexical_path") from None


def build(input_path: Path, output: Path, assets: Path | None = None) -> dict[str, Any]:
    """Backup one generation and publish only a closed, fully validated extension."""
    from app.config import load_embedding_settings
    from app.semantic_storage import SemanticReader, SemanticStorageError
    protect_paths(input_path, output, assets if assets is not None else load_embedding_settings().model_path)
    probe_fts5()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        source = sqlite3.connect(input_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(temporary)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        semantic = SemanticReader(temporary)
        vectors = _raw_vectors(temporary)
        metadata = lexical_metadata(semantic.snapshot)
        _write_extension(temporary, semantic.snapshot, metadata)
        reopened = SemanticReader(temporary)
        with LexicalReader(temporary) as lexical:
            if (reopened.snapshot != semantic.snapshot or reopened.metadata != semantic.metadata
                    or lexical.snapshot != semantic.snapshot or lexical.metadata != metadata
                    or _raw_vectors(temporary) != vectors):
                raise LexicalStorageError("lexical_build_validation")
        os.replace(temporary, output)
        return {"documents": len(semantic.snapshot.documents), "chunks": len(semantic.chunks), "identity": metadata}
    except (StorageError, SemanticStorageError, LexicalStorageError):
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError):
        raise LexicalStorageError("lexical_build") from None
    finally:
        if temporary is not None:
            for path in (temporary, Path(str(temporary) + "-journal"), Path(str(temporary) + "-wal"), Path(str(temporary) + "-shm")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ArgumentParser(description="Build a lossless offline FTS5 snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--model-path", type=Path)
    args = parser.parse_args(argv)
    from app.semantic_storage import SemanticStorageError
    try:
        report = build(args.input, args.output, args.model_path)
    except (StorageError, SemanticStorageError, LexicalStorageError) as error:
        print(f"lexical: {error}", file=sys.stderr)
        return 1
    except ValueError:
        print("lexical: configuration", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
