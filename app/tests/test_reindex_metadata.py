from dataclasses import replace
import sqlite3

import pytest

from app.index_storage import StorageReader
from app.reindex_metadata import ReindexMetadata, ReindexMetadataError, read_metadata, write_metadata
from app.semantic_storage import SemanticReader
from test_semantic_storage import semantic_file


def test_round_trip_and_old_readers(semantic_file):
    snapshot = SemanticReader(semantic_file).snapshot
    metadata = ReindexMetadata(1, "2026-10-20T09:00:00Z", len(snapshot.documents), len(snapshot.chunks))
    connection = sqlite3.connect(semantic_file)
    try:
        with connection:
            write_metadata(connection, metadata, snapshot)
    finally:
        connection.close()
    with StorageReader(semantic_file) as base:
        assert read_metadata(base) == metadata
    assert SemanticReader(semantic_file).snapshot == snapshot


@pytest.mark.parametrize("key,value", [
    ("format_version", 2), ("format_version", True), ("indexed_at", "2026-10-20"),
    ("indexed_at", "2026-10-20T09:00:00+03:00"), ("indexed_at", "2026-02-30T09:00:00Z"),
    ("document_count", -1), ("chunk_count", 999), ("chunk_count", True),
])
def test_invalid_metadata(semantic_file, key, value):
    snapshot = SemanticReader(semantic_file).snapshot
    meta = ReindexMetadata(1, "2026-10-20T09:00:00Z", len(snapshot.documents), len(snapshot.chunks))
    connection = sqlite3.connect(semantic_file)
    try:
        with pytest.raises(ReindexMetadataError):
            write_metadata(connection, replace(meta, **{key: value}), snapshot)
    finally:
        connection.close()


@pytest.mark.parametrize("column,value", [
    ("format_version", 99), ("indexed_at", "2026-10-20"),
    ("indexed_at", "2026-10-20T09:00:00+03:00"), ("document_count", 99), ("chunk_count", -1),
])
def test_reader_rejects_invalid_metadata(semantic_file, column, value):
    snapshot = SemanticReader(semantic_file).snapshot
    connection = sqlite3.connect(semantic_file)
    try:
        with connection:
            write_metadata(connection, ReindexMetadata(1, "2026-10-20T09:00:00Z",
                           len(snapshot.documents), len(snapshot.chunks)), snapshot)
            connection.execute(f"UPDATE reindex_metadata SET {column}=?", (value,))
    finally:
        connection.close()
    with StorageReader(semantic_file) as base:
        with pytest.raises(ReindexMetadataError):
            read_metadata(base)
