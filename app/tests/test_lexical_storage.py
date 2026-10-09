import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.index_storage import StorageError, StorageReader
from app.lexical_storage import LexicalReader, LexicalStorageError, build, probe_fts5
from app.semantic_storage import SemanticReader, write_semantic
from test_semantic_storage import metadata, semantic_snapshot, unit_matrix


@pytest.fixture
def semantic_file(tmp_path):
    path = tmp_path / "semantic.db"
    snapshot = semantic_snapshot()
    write_semantic(path, snapshot, unit_matrix(len(snapshot.chunks)), metadata())
    return path


@pytest.fixture
def lexical_file(semantic_file):
    path = semantic_file.with_name("lexical.db")
    build(semantic_file, path, path.parent / "absent-assets")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_round_trip_and_repeated_build(semantic_file, lexical_file, monkeypatch):
    monkeypatch.setattr("app.embeddings.LocalEncoder.encode_passages", lambda *args: pytest.fail("inference"))
    monkeypatch.setattr("app.embeddings.LocalEncoder.encode_query", lambda *args: pytest.fail("inference"))
    before = digest(semantic_file), digest(lexical_file)
    with LexicalReader(lexical_file) as reader, StorageReader(semantic_file) as base:
        assert reader.snapshot == base.snapshot
        assert reader.metadata["format_version"] == 1
        assert reader.metadata["chunks"] == 1
    assert before == (digest(semantic_file), digest(lexical_file))
    output = lexical_file.with_name("rebuilt.db")
    build(lexical_file, output)
    with LexicalReader(output) as reader:
        assert reader.snapshot == SemanticReader(semantic_file).snapshot
    for path in (semantic_file, lexical_file, output):
        with sqlite3.connect(path) as connection:
            vectors = connection.execute("SELECT chunk_id, vector FROM chunk_embeddings").fetchall()
            assert vectors == [("b" * 64, unit_matrix(1)[0].tobytes())]


@pytest.mark.parametrize("sql", [
    "DELETE FROM chunk_fts",
    "INSERT INTO chunk_fts(chunk_id,title,heading_path,search_text) SELECT chunk_id,title,heading_path,search_text FROM chunk_fts",
    "INSERT INTO chunk_fts VALUES ('extra','title','heading','text')",
    "UPDATE chunk_fts SET title='stale'",
    "UPDATE chunk_fts SET heading_path='stale'",
    "UPDATE chunk_fts SET search_text='stale'",
    "DROP TABLE chunk_fts",
    "UPDATE lexical_metadata SET metadata='{}'",
])
def test_content_inventory_corruption(lexical_file, sql):
    with sqlite3.connect(lexical_file) as connection:
        connection.execute(sql)
        if sql.startswith("UPDATE chunk_fts"):
            # A self-consistent but stale FTS passes SQLite's internal check.
            connection.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')")
    before = digest(lexical_file)
    with pytest.raises(LexicalStorageError):
        LexicalReader(lexical_file)
    assert digest(lexical_file) == before


@pytest.mark.parametrize("key,value", [("format_version", 2), ("query_policy_version", True),
                                       ("literal_policy_version", 2), ("input_format_version", 2),
                                       ("options", {"tokenizer": "porter"}), ("chunks", 7)])
def test_metadata_versions(lexical_file, key, value):
    with sqlite3.connect(lexical_file) as connection:
        data = json.loads(connection.execute("SELECT metadata FROM lexical_metadata").fetchone()[0])
        data[key] = value
        connection.execute("UPDATE lexical_metadata SET metadata=?", (json.dumps(data),))
    with pytest.raises(LexicalStorageError):
        LexicalReader(lexical_file)


def test_options_postings_base_corruption(lexical_file):
    with sqlite3.connect(lexical_file) as connection:
        connection.execute("UPDATE chunk_fts_data SET block=x'00' WHERE id>10")
    before = digest(lexical_file)
    with pytest.raises((StorageError, LexicalStorageError)):
        LexicalReader(lexical_file)
    assert digest(lexical_file) == before


@pytest.mark.parametrize("sql", ["UPDATE documents SET markdown='bad'", "UPDATE chunks SET search_text='bad'",
                                 "PRAGMA user_version=2"])
def test_base_corruption(lexical_file, sql):
    with sqlite3.connect(lexical_file) as connection:
        connection.execute(sql)
    with pytest.raises(StorageError):
        LexicalReader(lexical_file)


def test_missing_and_semantic_only(tmp_path, semantic_file):
    path = tmp_path / "missing.db"
    with pytest.raises(StorageError):
        LexicalReader(path)
    assert not path.exists()
    with pytest.raises(LexicalStorageError, match="lexical_schema"):
        LexicalReader(semantic_file)


def test_missing_fts(monkeypatch):
    original = sqlite3.connect
    class NoFTS:
        def execute(self, *args):
            raise sqlite3.OperationalError("backend secret")
        def close(self):
            pass
    monkeypatch.setattr(sqlite3, "connect", lambda *args: NoFTS())
    with pytest.raises(LexicalStorageError, match="^lexical_capability$"):
        probe_fts5()
    monkeypatch.setattr(sqlite3, "connect", original)


def test_empty_removed_inventory(semantic_file, lexical_file):
    snapshot = semantic_snapshot(empty=True)
    write_semantic(semantic_file, snapshot, unit_matrix(0), metadata())
    build(semantic_file, lexical_file)
    with LexicalReader(lexical_file) as reader:
        assert reader.chunks == ()
        assert reader.metadata["chunks"] == 0
        assert reader.snapshot == snapshot


@pytest.mark.parametrize("stage", ["_write_extension", "validate_lexical", "os.replace"])
def test_failure_preservation(semantic_file, lexical_file, monkeypatch, stage):
    before = digest(semantic_file), digest(lexical_file)
    def fail(*args):
        raise OSError("backend secret")
    monkeypatch.setattr("app.lexical_storage." + stage, fail)
    with pytest.raises(LexicalStorageError, match="^lexical_build$"):
        build(semantic_file, lexical_file)
    assert before == (digest(semantic_file), digest(lexical_file))
    assert not list(lexical_file.parent.glob("*.tmp"))


def test_schema_options_rejected(lexical_file):
    with sqlite3.connect(lexical_file) as connection:
        connection.execute("DROP TABLE chunk_fts")
        connection.execute("CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED,title,heading_path,search_text,tokenize='porter')")
    with pytest.raises(LexicalStorageError, match="lexical_schema"):
        LexicalReader(lexical_file)
