"""Additive full-reindex metadata; no changes to existing format versions."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
import sqlite3

from app.index_storage import StorageReader, StorageSnapshot


class ReindexMetadataError(ValueError):
    """Safe metadata category."""


@dataclass(frozen=True)
class ReindexMetadata:
    format_version: int
    indexed_at: str
    document_count: int
    chunk_count: int


def validate(metadata: ReindexMetadata, snapshot: StorageSnapshot) -> None:
    if type(metadata.format_version) is not int or metadata.format_version != 1:
        raise ReindexMetadataError("reindex_version")
    try:
        if not isinstance(metadata.indexed_at, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", metadata.indexed_at
        ):
            raise ValueError
        if datetime.fromisoformat(metadata.indexed_at).utcoffset() != timedelta(0):
            raise ValueError
    except (ValueError, TypeError):
        raise ReindexMetadataError("reindex_time") from None
    for value, expected in ((metadata.document_count, len(snapshot.documents)),
                            (metadata.chunk_count, len(snapshot.chunks))):
        if type(value) is not int or value != expected:
            raise ReindexMetadataError("reindex_counts")


def write_metadata(connection: sqlite3.Connection, metadata: ReindexMetadata, snapshot: StorageSnapshot) -> None:
    validate(metadata, snapshot)
    connection.execute("""CREATE TABLE reindex_metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), format_version INTEGER NOT NULL,
        indexed_at TEXT NOT NULL, document_count INTEGER NOT NULL, chunk_count INTEGER NOT NULL
    )""")
    connection.execute("INSERT INTO reindex_metadata VALUES (1, ?, ?, ?, ?)",
                       (metadata.format_version, metadata.indexed_at, metadata.document_count, metadata.chunk_count))


def read_metadata(base: StorageReader) -> ReindexMetadata:
    connection = base._connection
    if connection is None:
        raise ReindexMetadataError("reindex_closed")
    try:
        rows = connection.execute(
            "SELECT singleton, format_version, indexed_at, document_count, chunk_count FROM reindex_metadata"
        ).fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise ReindexMetadataError("reindex_metadata")
        metadata = ReindexMetadata(*tuple(rows[0])[1:])
        validate(metadata, base.snapshot)
        return metadata
    except sqlite3.Error:
        raise ReindexMetadataError("reindex_metadata") from None
