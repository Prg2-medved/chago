from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

from app.chunk_tokenizer import ASSET_HASHES, MODEL_ID, REVISION
from app.index_storage import StorageError, StorageReader, parse_output, write_snapshot
from app.semantic_storage import SemanticReader, SemanticStorageError, expected_identity, protect_paths, write_semantic
from test_index_storage import output


def semantic_snapshot(empty=False):
    data = output("" if empty else "Русский ```code``` | table |")
    data["tokenizer"] = {
        "model_id": MODEL_ID, "revision": REVISION, "assets_sha256": ASSET_HASHES,
        "assets_fingerprint": expected_identity()["tokenizer_fingerprint"],
        "package": "tokenizers", "package_version": "0.22.2",
    }
    return parse_output(data)


def metadata():
    return {**expected_identity(), "format_version": 1,
            "runtime": {name: "test" for name in ("torch", "numpy", "sentence-transformers", "transformers", "tokenizers")}}


def unit_matrix(count):
    matrix = np.zeros((count, 384), dtype="<f4")
    for i in range(count):
        matrix[i, i % 384] = 1
    return matrix


@pytest.fixture
def semantic_file(tmp_path):
    path = tmp_path / "semantic.db"
    snapshot = semantic_snapshot()
    write_semantic(path, snapshot, unit_matrix(len(snapshot.chunks)), metadata())
    return path


def test_reopen_base_provenance_immutable(semantic_file):
    before = semantic_file.read_bytes()
    reader = SemanticReader(semantic_file)
    with StorageReader(semantic_file) as base:
        assert base.snapshot == reader.snapshot == semantic_snapshot()
    assert reader.matrix[0, 0] == 1
    with pytest.raises(ValueError):
        reader.matrix.setflags(write=True)
    assert semantic_file.read_bytes() == before


def test_base_health_without_model_dependencies(semantic_file):
    code = """
import sys
for name in ('numpy', 'torch', 'sentence_transformers', 'transformers', 'tokenizers'):
    sys.modules[name] = None
from pathlib import Path
from app.index_storage import StorageReader
from app.config import load_settings
from app.main import app
from fastapi.testclient import TestClient
assert load_settings().port == 8000
with StorageReader(Path(sys.argv[1])) as reader:
    assert len(reader.chunks) == 1
with TestClient(app) as client:
    assert client.get('/health').json() == {'status': 'ok'}
"""
    result = subprocess.run([sys.executable, "-c", code, str(semantic_file)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_empty_removed_inventory(semantic_file):
    snapshot = semantic_snapshot(empty=True)
    write_semantic(semantic_file, snapshot, unit_matrix(0), metadata())
    assert SemanticReader(semantic_file).matrix.shape == (0, 384)
    assert SemanticReader(semantic_file).chunks == ()


@pytest.mark.parametrize("key,value", [
    ("format_version", 2), ("dimension", 383), ("dtype", ">f4"), ("normalized", False),
    ("model_id", "other"), ("revision", "other"), ("assets_fingerprint", "f" * 64),
    ("tokenizer_fingerprint", "f" * 64), ("input_format_version", 2), ("runtime", {}),
])
def test_invalid_metadata(semantic_file, key, value):
    meta = metadata()
    meta[key] = value
    with sqlite3.connect(semantic_file) as connection:
        connection.execute("UPDATE embedding_metadata SET metadata=?", (json.dumps(meta),))
    with pytest.raises(SemanticStorageError):
        SemanticReader(semantic_file)


@pytest.mark.parametrize("value", [b"short", b"\0" * 1536, np.full(384, np.nan, dtype="<f4").tobytes(), np.ones(384, dtype="<f4").tobytes()])
def test_invalid_vectors(semantic_file, value):
    with sqlite3.connect(semantic_file) as connection:
        connection.execute("UPDATE chunk_embeddings SET vector=?", (value,))
    with pytest.raises(SemanticStorageError, match="semantic_vectors"):
        SemanticReader(semantic_file)


@pytest.mark.parametrize("sql", [
    "DELETE FROM chunk_embeddings",
    "INSERT INTO chunk_embeddings VALUES ('extra', zeroblob(1536))",
    "DROP TABLE chunk_embeddings",
    "ALTER TABLE chunk_embeddings RENAME TO old_vectors",
    "UPDATE embedding_metadata SET metadata='invalid json'",
])
def test_schema_coverage(semantic_file, sql):
    with sqlite3.connect(semantic_file) as connection:
        connection.execute(sql)
    with pytest.raises((StorageError, SemanticStorageError)):
        SemanticReader(semantic_file)


@pytest.mark.parametrize("sql", [
    "PRAGMA user_version=2", "DROP TABLE chunks",
    "ALTER TABLE documents RENAME COLUMN title TO broken",
    "UPDATE chunks SET segments='invalid json'",
    "UPDATE chunks SET search_text='wrong provenance'",
    "UPDATE documents SET markdown='wrong hash'",
])
def test_base_validation_first(semantic_file, sql):
    with sqlite3.connect(semantic_file) as connection:
        connection.execute(sql)
    for reader in (StorageReader, SemanticReader):
        with pytest.raises(StorageError):
            reader(semantic_file)


@pytest.mark.parametrize("table,old,new", [
    ("chunks", "PRIMARY KEY NOT NULL", "NOT NULL"),
    ("chunks", "UNIQUE(source, page_id, ordinal)", "UNIQUE(source, page_id, ordinal, search_text)"),
    ("chunks", "REFERENCES documents(source, page_id)", "REFERENCES documents(page_id, source)"),
    ("chunk_embeddings", "PRIMARY KEY NOT NULL", "NOT NULL"),
    ("chunk_embeddings", "REFERENCES chunks(chunk_id)", "REFERENCES chunks(search_text)"),
])
def test_schema_keys(semantic_file, table, old, new):
    with sqlite3.connect(semantic_file) as connection:
        sql = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        assert old in sql
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute("UPDATE sqlite_master SET sql=? WHERE name=?", (sql.replace(old, new), table))
    if table == "chunks":
        with pytest.raises(StorageError):
            StorageReader(semantic_file)
    with pytest.raises((StorageError, SemanticStorageError)):
        SemanticReader(semantic_file)


def test_read_missing_storage_only(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(StorageError):
        SemanticReader(missing)
    assert not missing.exists()
    write_snapshot(missing, semantic_snapshot())
    with pytest.raises(SemanticStorageError):
        SemanticReader(missing)


def test_write_failure_preserves_previous(semantic_file, monkeypatch):
    before = semantic_file.read_bytes()
    def fail(*args):
        raise OSError("sensitive-source")
    monkeypatch.setattr("app.semantic_storage.os.replace", fail)
    snapshot = semantic_snapshot()
    with pytest.raises(SemanticStorageError, match="semantic_write") as error:
        write_semantic(semantic_file, snapshot, unit_matrix(1), metadata())
    assert "sensitive" not in str(error.value)
    assert semantic_file.read_bytes() == before
    assert not list(semantic_file.parent.glob("*.tmp"))


def test_protected_aliases(tmp_path):
    source = tmp_path / "source.db"
    source.write_bytes(b"source")
    assets = tmp_path / "assets"
    assets.mkdir()
    alias = tmp_path / "alias.db"
    alias.hardlink_to(source)
    for target in (source, alias, assets / "index.db"):
        with pytest.raises(SemanticStorageError, match="semantic_path"):
            protect_paths(source, target, assets)
    asset = assets / "model.safetensors"
    asset.write_bytes(b"asset")
    asset_alias = tmp_path / "asset.db"
    asset_alias.hardlink_to(asset)
    with pytest.raises(SemanticStorageError, match="semantic_path"):
        protect_paths(source, asset_alias, assets)
