"""Validated offline chunk snapshots, atomic SQLite persistence and read-only access."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any
from urllib.parse import quote, urlsplit

from app.ingestion import Document


STORAGE_VERSION = 1


class StorageError(ValueError):
    """Safe categories, never source text or filesystem diagnostics."""


@dataclass(frozen=True)
class StoredChunk:
    chunk_id: str
    source: str
    document: Document
    heading_path: tuple[str, ...]
    ordinal: int
    segments: tuple[dict[str, Any], ...]
    source_ranges: tuple[tuple[int, int], ...]
    search_text: str
    body_tokens: int
    input_tokens: int
    structure: dict[str, Any]


@dataclass(frozen=True)
class StorageSnapshot:
    source: str
    schema_version: int
    algorithm_version: str
    tokenizer: dict[str, Any]
    settings: dict[str, int]
    documents: tuple[Document, ...]
    chunks: tuple[StoredChunk, ...]


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise StorageError("validation")
    return value


def _text(value: object, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise StorageError("validation")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise StorageError("validation") from None
    return value


def _integer(value: object, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise StorageError("validation")
    return value


def _digest(value: object) -> str:
    text = _text(value)
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise StorageError("validation")
    return text


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError):
        raise StorageError("validation") from None


def parse_output(payload: object) -> StorageSnapshot:
    """Validate output v1 without loading assets or recalculating E5 counts."""
    row = _object(payload)
    if _integer(row.get("schema_version")) != 1:
        raise StorageError("input_version")
    source = _text(row.get("source"))
    try:
        parts = urlsplit(source)
        valid = (parts.scheme in ("http", "https") and bool(parts.hostname)
                 and parts.username is None and parts.password is None
                 and not parts.path and not parts.query and not parts.fragment
                 and parts.port != 0 and not any(char.isspace() for char in source))
    except ValueError:
        valid = False
    if not valid:
        raise StorageError("validation")
    algorithm = _text(row.get("algorithm_version"))
    tokenizer = _object(row.get("tokenizer"))
    for name in ("model_id", "revision", "package", "package_version"):
        _text(tokenizer.get(name))
    hashes = _object(tokenizer.get("assets_sha256"))
    if not hashes:
        raise StorageError("validation")
    for name, digest in hashes.items():
        _text(name)
        _digest(digest)
    if _digest(tokenizer.get("assets_fingerprint")) != hashlib.sha256(_json(hashes).encode()).hexdigest():
        raise StorageError("validation")
    raw_settings = _object(row.get("settings"))
    settings = {name: _integer(raw_settings.get(name))
                for name in ("target", "maximum", "overlap", "input_limit")}
    if (set(raw_settings) != set(settings)
            or not 0 <= settings["overlap"] < settings["target"] <= settings["maximum"] <= 450
            or not 1 <= settings["input_limit"] <= 512):
        raise StorageError("validation")
    raw_documents, raw_chunks = row.get("documents"), row.get("chunks")
    if not isinstance(raw_documents, list) or not isinstance(raw_chunks, list):
        raise StorageError("validation")
    documents: dict[int, Document] = {}
    identities: set[tuple[str, str]] = set()
    for raw in raw_documents:
        doc = _object(raw)
        page_id = _integer(doc.get("page_id"), 1)
        values = {name: _text(doc.get(name), empty=name == "markdown") for name in
                  ("locale", "path", "title", "source_url", "updated_at", "markdown", "content_sha256")}
        identity = (values["locale"], values["path"])
        if page_id in documents or identity in identities:
            raise StorageError("validation")
        if values["source_url"] != f"{source}/{quote(values['locale'], safe='')}/{quote(values['path'], safe='/')}":
            raise StorageError("validation")
        timestamp = values["updated_at"]
        try:
            if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", timestamp)
                    or datetime.fromisoformat(timestamp).utcoffset() is None):
                raise ValueError
        except ValueError:
            raise StorageError("validation") from None
        if values["content_sha256"] != hashlib.sha256(values["markdown"].encode()).hexdigest():
            raise StorageError("validation")
        documents[page_id] = Document(page_id=page_id, **values)
        identities.add(identity)
    chunks: list[StoredChunk] = []
    ids: set[str] = set()
    ordinals: set[tuple[int, int]] = set()
    for raw in raw_chunks:
        chunk = _object(raw)
        chunk_id = _digest(chunk.get("chunk_id"))
        page_id = _integer(chunk.get("page_id"), 1)
        document = documents.get(page_id)
        if document is None or chunk.get("source") != source or chunk_id in ids:
            raise StorageError("validation")
        for name, value in asdict(document).items():
            if name != "markdown" and (type(chunk.get(name)) is not type(value) or chunk.get(name) != value):
                raise StorageError("validation")
        ordinal = _integer(chunk.get("ordinal"))
        if (page_id, ordinal) in ordinals:
            raise StorageError("validation")
        headings = chunk.get("heading_path")
        if not isinstance(headings, (list, tuple)):
            raise StorageError("validation")
        heading_path = tuple(_text(value, empty=True) for value in headings)
        raw_segments = chunk.get("segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            raise StorageError("validation")
        segments: list[dict[str, Any]] = []
        ranges: list[tuple[int, int]] = []
        texts: list[str] = []
        for raw_segment in raw_segments:
            segment = _object(raw_segment)
            if segment.get("kind") == "source":
                start = _integer(segment.get("start"))
                end = _integer(segment.get("end"), start + 1, len(document.markdown))
                if segment.get("role") not in ("text", "heading", "code", "table", "table_header", "table_row", "overlap"):
                    raise StorageError("validation")
                ranges.append((start, end))
                texts.append(document.markdown[start:end])
            elif segment.get("kind") == "generated":
                if segment.get("reason") not in ("table_header", "fence", "separator"):
                    raise StorageError("validation")
                texts.append(_text(segment.get("text"), empty=True))
            else:
                raise StorageError("validation")
            segments.append(segment)
        raw_ranges = chunk.get("source_ranges")
        if not isinstance(raw_ranges, list) or not ranges:
            raise StorageError("validation")
        checked_ranges = []
        for pair in raw_ranges:
            if not isinstance(pair, list) or len(pair) != 2:
                raise StorageError("validation")
            checked_ranges.append((_integer(pair[0]), _integer(pair[1])))
        search_text = _text(chunk.get("search_text"), empty=True)
        if checked_ranges != ranges or search_text != "".join(texts):
            raise StorageError("validation")
        body_tokens = _integer(chunk.get("body_tokens"), 0, settings["maximum"])
        input_tokens = _integer(chunk.get("input_tokens"), body_tokens, settings["input_limit"])
        structure = _object(chunk.get("structure"))
        _json(structure)
        chunks.append(StoredChunk(chunk_id, source, document, heading_path, ordinal,
                                  tuple(segments), tuple(ranges), search_text,
                                  body_tokens, input_tokens, structure))
        ids.add(chunk_id)
        ordinals.add((page_id, ordinal))
    for page_id in documents:
        sequence = sorted(ordinal for doc_id, ordinal in ordinals if doc_id == page_id)
        if sequence != list(range(len(sequence))):
            raise StorageError("validation")
    # Detach nested mutable input and reject non-JSON values before any write.
    tokenizer = json.loads(_json(tokenizer))
    chunks = [StoredChunk(**{**chunk.__dict__, "segments": tuple(json.loads(_json(chunk.segments))),
                             "structure": json.loads(_json(chunk.structure))}) for chunk in chunks]
    return StorageSnapshot(source, 1, algorithm, tokenizer, settings,
                           tuple(sorted(documents.values(), key=lambda doc: doc.page_id)),
                           tuple(sorted(chunks, key=lambda chunk: (chunk.document.page_id, chunk.ordinal, chunk.chunk_id))))


def load_output(path: Path) -> StorageSnapshot:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        raise StorageError("input_read") from None
    return parse_output(payload)


_SCHEMA = """
PRAGMA user_version=1;
CREATE TABLE snapshot_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    source TEXT NOT NULL, input_schema_version INTEGER NOT NULL,
    algorithm_version TEXT NOT NULL, tokenizer TEXT NOT NULL, settings TEXT NOT NULL
);
CREATE TABLE documents (
    source TEXT NOT NULL, page_id INTEGER NOT NULL,
    locale TEXT NOT NULL, path TEXT NOT NULL, title TEXT NOT NULL,
    source_url TEXT NOT NULL, updated_at TEXT NOT NULL,
    markdown TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    PRIMARY KEY(source, page_id), UNIQUE(source, locale, path)
);
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY NOT NULL, source TEXT NOT NULL, page_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL, heading_path TEXT NOT NULL, segments TEXT NOT NULL,
    source_ranges TEXT NOT NULL, search_text TEXT NOT NULL,
    body_tokens INTEGER NOT NULL, input_tokens INTEGER NOT NULL, structure TEXT NOT NULL,
    UNIQUE(source, page_id, ordinal),
    FOREIGN KEY(source, page_id) REFERENCES documents(source, page_id)
);
"""


def _check_schema(connection: sqlite3.Connection) -> None:
    reference = sqlite3.connect(":memory:")
    try:
        reference.executescript(_SCHEMA)
        for table in ("snapshot_metadata", "documents", "chunks"):
            for pragma in ("table_info", "foreign_key_list"):
                actual = [tuple(row) for row in connection.execute(f"PRAGMA {pragma}({table})")]
                expected = reference.execute(f"PRAGMA {pragma}({table})").fetchall()
                if actual != expected:
                    raise StorageError("storage_schema")

            def unique_keys(database: sqlite3.Connection) -> set[tuple[str, ...]]:
                keys = set()
                for index in database.execute(f"PRAGMA index_list({table})"):
                    if index[2]:
                        # Names originate in SQLite, quote before using as identifiers.
                        name = index[1].replace('"', '""')
                        keys.add(tuple(row[2] for row in database.execute(f'PRAGMA index_info("{name}")')))
                return keys

            if unique_keys(connection) != unique_keys(reference):
                raise StorageError("storage_schema")
    finally:
        reference.close()


def _write_database(path: Path, snapshot: StorageSnapshot) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.executescript(_SCHEMA)
        with connection:
            connection.execute("INSERT INTO snapshot_metadata VALUES (1, ?, ?, ?, ?, ?)",
                               (snapshot.source, snapshot.schema_version, snapshot.algorithm_version,
                                _json(snapshot.tokenizer), _json(snapshot.settings)))
            connection.executemany("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   [(snapshot.source, *asdict(doc).values()) for doc in snapshot.documents])
            connection.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   [(chunk.chunk_id, chunk.source, chunk.document.page_id, chunk.ordinal,
                                     _json(chunk.heading_path), _json(chunk.segments), _json(chunk.source_ranges),
                                     chunk.search_text, chunk.body_tokens, chunk.input_tokens, _json(chunk.structure))
                                    for chunk in snapshot.chunks])
    finally:
        connection.close()


class StorageReader:
    """Read-only, validated snapshot; close before publishing another file on Windows."""

    def __init__(self, path: Path) -> None:
        self._connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            self._connection = connection
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA user_version").fetchone()[0] != STORAGE_VERSION:
                raise StorageError("storage_version")
            _check_schema(connection)
            if ([row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]
                    or connection.execute("PRAGMA foreign_key_check").fetchall()):
                raise StorageError("storage_integrity")
            metadata = connection.execute("SELECT singleton, source, input_schema_version, algorithm_version, tokenizer, settings FROM snapshot_metadata").fetchall()
            if len(metadata) != 1 or metadata[0]["singleton"] != 1:
                raise StorageError("storage_integrity")
            meta = metadata[0]
            documents = []
            for row in connection.execute("SELECT source, page_id, locale, path, title, source_url, updated_at, markdown, content_sha256 FROM documents ORDER BY source, page_id"):
                if row["source"] != meta["source"]:
                    raise StorageError("storage_integrity")
                documents.append({key: row[key] for key in row.keys() if key != "source"})
            by_id = {doc["page_id"]: doc for doc in documents}
            chunks = []
            for row in connection.execute("SELECT chunk_id, source, page_id, ordinal, heading_path, segments, source_ranges, search_text, body_tokens, input_tokens, structure FROM chunks ORDER BY source, page_id, ordinal, chunk_id"):
                doc = by_id.get(row["page_id"])
                if doc is None:
                    raise StorageError("storage_integrity")
                chunk = {key: row[key] for key in row.keys()}
                for key in ("heading_path", "segments", "source_ranges", "structure"):
                    chunk[key] = json.loads(chunk[key])
                chunks.append({**{key: value for key, value in doc.items() if key != "markdown"}, **chunk})
            self.snapshot = parse_output({"schema_version": meta["input_schema_version"],
                                          "source": meta["source"], "algorithm_version": meta["algorithm_version"],
                                          "tokenizer": json.loads(meta["tokenizer"]), "settings": json.loads(meta["settings"]),
                                          "documents": documents, "chunks": chunks})
            self._chunks = {chunk.chunk_id: chunk for chunk in self.snapshot.chunks}
        except StorageError:
            self.close()
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            self.close()
            raise StorageError("storage_read") from None

    @property
    def documents(self) -> tuple[Document, ...]:
        return self.snapshot.documents

    @property
    def chunks(self) -> tuple[StoredChunk, ...]:
        return self.snapshot.chunks

    def get_chunk(self, chunk_id: str) -> StoredChunk | None:
        return self._chunks.get(chunk_id)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "StorageReader":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def write_snapshot(output: Path, snapshot: StorageSnapshot) -> None:
    """Publish only a closed, verified complete snapshot; preserve the old file on failure."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        _write_database(temporary, snapshot)
        with StorageReader(temporary) as reader:
            if reader.snapshot != snapshot:
                raise StorageError("storage_integrity")
        os.replace(temporary, output)
    except (sqlite3.Error, OSError, ValueError, TypeError):
        raise StorageError("output_write") from None
    finally:
        if temporary is not None:
            for path in (temporary, Path(str(temporary) + "-journal")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def protect_paths(input_path: Path, output: Path) -> None:
    try:
        if input_path.resolve() == output.resolve() or (output.exists() and input_path.samefile(output)):
            raise StorageError("output_path")
    except OSError:
        raise StorageError("output_path") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save a validated storage-only SQLite snapshot")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        protect_paths(arguments.input, arguments.output)
        snapshot = load_output(arguments.input)
        write_snapshot(arguments.output, snapshot)
    except StorageError as error:
        print(f"storage: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"documents": len(snapshot.documents), "chunks": len(snapshot.chunks),
                      "storage_version": STORAGE_VERSION}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
