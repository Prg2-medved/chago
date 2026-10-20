from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import MagicMock

import psycopg
import pytest

from app import indexer
from app.wiki_client import fetch_pages
from app.config import EmbeddingSettings, IngestionSettings
from app.index_state import ActiveIndex
from app.hybrid_retrieval import HybridIndex
from app.semantic_storage import expected_identity
from test_semantic_storage import metadata, semantic_snapshot, unit_matrix


class Tokenizer:
    identity = semantic_snapshot().tokenizer

    def count(self, text, special=False):
        return len(text.split()) + (2 if special else 0)

    def offsets(self, text):
        # Character tokens allow deterministic oversized block splitting in fixtures.
        return [(i, i + 1) for i in range(len(text))]


class Encoder:
    tokenizer = Tokenizer()
    identity = expected_identity()

    def __init__(self, settings):
        self.settings = settings

    def encode_passages(self, chunks):
        return unit_matrix(len(chunks))

    def encode_query(self, question):
        return unit_matrix(1)[0]

    def runtime(self):
        return metadata()["runtime"]


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    active = tmp_path / "index.sqlite3"
    assets = tmp_path / "models"
    assets.mkdir()
    monkeypatch.setenv("INDEX_PATH", str(active))
    monkeypatch.setattr(indexer, "load_embedding_settings", lambda: EmbeddingSettings(assets))
    monkeypatch.setattr(indexer, "load_ingestion_settings", lambda: IngestionSettings(
        "host", "db", "reader", "fixture-secret", "https://wiki.example"))
    monkeypatch.setattr(indexer, "LocalEncoder", Encoder)
    # Portable pipeline tests explicitly substitute the Linux-only lock.
    monkeypatch.setattr(indexer, "builder_lock", lambda path: nullcontext())
    rows = [{"page_id": 1, "locale": "ru", "path": "test", "title": "Title",
             "markdown": "# Heading\r\n```py\r\nx=1\r\n```\r\n\r\n| a | b |\r\n|---|---|\r\n| x | y |\r\n",
             "updated_at": "2026-10-20T00:00:00Z"}]
    monkeypatch.setattr("app.ingestion.fetch_pages", lambda settings: rows.copy())
    return active, rows, assets


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_pipeline_update_delete_empty_reopen(pipeline):
    active, rows, _ = pipeline
    report = indexer.rebuild()
    assert report["document_count"] == 1 and report["chunk_count"] > 0
    with ActiveIndex(active) as ready:
        assert ready.snapshot.documents[0].markdown == rows[0]["markdown"]
        assert ready.ordered_ids == tuple(sorted(chunk.chunk_id for chunk in ready.snapshot.chunks))
        assert ready.matrix.shape == (len(ready.ordered_ids), 384)
        for chunk in ready.snapshot.chunks:
            for segment in chunk.segments:
                if segment["kind"] == "source":
                    assert rows[0]["markdown"][segment["start"]:segment["end"]] in chunk.search_text
        first_time = ready.metadata.indexed_at
        expected_ids = ready.ordered_ids
        vector_columns = [next(i for i, chunk in enumerate(ready.snapshot.chunks) if chunk.chunk_id == chunk_id)
                          for chunk_id in expected_ids]
    reopen = """
import json,sys
from pathlib import Path
from app.index_state import ActiveIndex
ids,columns,timestamp = json.loads(sys.argv[2])
with ActiveIndex(Path(sys.argv[1])) as ready:
    assert list(ready.ordered_ids) == ids
    assert ready.metadata.indexed_at == timestamp
    assert ready.metadata.document_count == 1
    assert ready.metadata.chunk_count == len(ids)
    assert ready.matrix.argmax(axis=1).tolist() == columns
    assert ready.matrix.sum(axis=1).tolist() == [1]*len(ids)
"""
    result = subprocess.run([sys.executable, "-c", reopen, str(active),
                             json.dumps([expected_ids, vector_columns, first_time])], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    rows[0]["markdown"] = "Updated unique page"
    indexer.rebuild()
    with ActiveIndex(active) as ready:
        assert ready.snapshot.documents[0].markdown == "Updated unique page"
        assert ready.metadata.indexed_at != first_time
    rows.clear()
    indexer.rebuild()
    assert not list(active.parent.glob(".*.reindex-*"))
    code = """
import sys
from pathlib import Path
from app.index_state import ActiveIndex
with ActiveIndex(Path(sys.argv[1])) as ready:
    assert ready.snapshot.documents == ()
    assert ready.ordered_ids == () and ready.matrix.shape == (0,384)
    assert ready.metadata.document_count == ready.metadata.chunk_count == 0
"""
    result = subprocess.run([sys.executable, "-c", code, str(active)], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("stage", ["source", "chunking", "assets", "base_write", "inference", "semantic", "lexical", "metadata", "candidate", "replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_failure_preserves_generation(pipeline, monkeypatch, stage, existing):
    active, _, _ = pipeline
    if existing:
        indexer.rebuild()
        before = fingerprint(active)
    foreign = active.parent / ".foreign.reindex-staging"
    foreign.mkdir()
    def fail(*args, **kwargs):
        raise OSError("fixture-secret postgres://credentials Markdown payload disk full")
    target, attribute = {
        "source": (indexer.ingestion, "ingest"), "chunking": (indexer.chunking, "build_output"),
        "assets": (indexer, "LocalEncoder"), "semantic": (indexer.semantic_storage, "build"),
        "base_write": (indexer.index_storage, "write_snapshot"), "inference": (Encoder, "encode_passages"),
        "lexical": (indexer.lexical_storage, "build"), "metadata": (indexer, "write_metadata"),
        "candidate": (indexer, "ActiveIndex"), "replace": (indexer.os, "replace"),
    }[stage]
    original = getattr(target, attribute)
    if stage == "replace":
        def replace(source, destination):
            if Path(destination) == active:
                fail()
            return original(source, destination)
        monkeypatch.setattr(target, attribute, replace)
    else:
        monkeypatch.setattr(target, attribute, fail)
    with pytest.raises(Exception):
        indexer.rebuild()
    assert foreign.is_dir()
    assert not list(active.parent.glob(".index.sqlite3.reindex-*"))
    if existing:
        assert fingerprint(active) == before
        with ActiveIndex(active) as ready:
            assert ready.metadata.document_count == 1
        with HybridIndex(active, Encoder(indexer.load_embedding_settings())) as query:
            assert query.search("Heading")
    else:
        assert not active.exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("existing", [False, True])
def test_active_sidecars_fail_closed(pipeline, suffix, existing):
    active, _, _ = pipeline
    if existing:
        indexer.rebuild()
    sidecar = Path(str(active) + suffix)
    sidecar.write_bytes(b"")
    before = fingerprint(active) if existing else None
    with pytest.raises(indexer.ReindexError, match="sqlite_sidecars"):
        indexer.rebuild()
    assert sidecar.read_bytes() == b""
    assert (fingerprint(active) if existing else None) == before


def test_sidecar_appears_before_replace(pipeline, monkeypatch):
    active, _, _ = pipeline
    indexer.rebuild()
    before = fingerprint(active)
    normalize = indexer.normalize_candidate
    def with_sidecar(candidate):
        normalize(candidate)
        Path(str(active) + "-wal").write_bytes(b"foreign")
    monkeypatch.setattr(indexer, "normalize_candidate", with_sidecar)
    with pytest.raises(indexer.ReindexError):
        indexer.rebuild()
    assert fingerprint(active) == before
    assert Path(str(active) + "-wal").read_bytes() == b"foreign"


def test_wal_active_untouched(pipeline):
    active, _, _ = pipeline
    indexer.rebuild()
    connection = sqlite3.connect(active)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE extra (value TEXT)")
        connection.commit()
        paths = [active, Path(str(active) + "-wal"), Path(str(active) + "-shm")]
        before = [fingerprint(path) for path in paths]
        with pytest.raises(indexer.ReindexError):
            indexer.rebuild()
        assert [fingerprint(path) for path in paths] == before
    finally:
        connection.close()
    # A closed, checkpointed WAL file still has WAL-format header bytes.
    with pytest.raises(indexer.ReindexError, match="journal_format"):
        indexer.rebuild()


def test_candidate_normalization_and_busy_checkpoint(tmp_path):
    path = tmp_path / "candidate.db"
    writer = sqlite3.connect(path)
    reader = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE example (value TEXT)")
        writer.commit()
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM example").fetchall()
        writer.execute("INSERT INTO example VALUES ('committed')")
        writer.commit()
        with pytest.raises(indexer.ReindexError, match="checkpoint"):
            indexer.normalize_candidate(path)
        reader.close()
        writer.close()
        indexer.normalize_candidate(path)
        indexer.require_standalone(path)
        connection = sqlite3.connect(path)
        try:
            assert connection.execute("SELECT * FROM example").fetchall() == [("committed",)]
        finally:
            connection.close()
    finally:
        reader.close()
        writer.close()


def test_protected_paths(pipeline):
    active, _, assets = pipeline
    asset = assets / "model.bin"
    asset.write_bytes(b"weights")
    with pytest.raises(indexer.ReindexError):
        indexer.protect_output(asset, assets)
    os.link(asset, active)
    with pytest.raises(indexer.ReindexError):
        indexer.protect_output(active, assets)
    assert active.read_bytes() == b"weights"


@pytest.mark.parametrize("stage", ["connection", "select", "fetch", "commit", "row"])
def test_actual_ingestion_failure_preserves_active(pipeline, monkeypatch, stage):
    active, rows, _ = pipeline
    indexer.rebuild()
    before = fingerprint(active)
    connect = MagicMock()
    connection = connect.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    error = psycopg.OperationalError("fixture-secret postgres://private markdown")
    if stage == "connection":
        connect.side_effect = error
    elif stage == "select":
        cursor.execute.side_effect = error
    elif stage == "fetch":
        cursor.fetchall.side_effect = error
    elif stage == "commit":
        connect.return_value.__exit__.side_effect = error
    else:
        rows[0]["markdown"] = None
    monkeypatch.setattr("app.wiki_client.psycopg.connect", connect)
    monkeypatch.setattr(indexer.ingestion, "fetch_pages", fetch_pages)
    with pytest.raises(Exception):
        indexer.rebuild()
    assert fingerprint(active) == before
    with ActiveIndex(active) as ready:
        assert ready.metadata.document_count == 1


@pytest.mark.parametrize("damage", ["vectors", "fts", "metadata"])
def test_corrupt_candidate_rejected(pipeline, monkeypatch, damage):
    active, _, _ = pipeline
    indexer.rebuild()
    before = fingerprint(active)
    normalize = indexer.normalize_candidate
    def corrupt(candidate):
        normalize(candidate)
        connection = sqlite3.connect(candidate)
        try:
            with connection:
                if damage == "vectors":
                    connection.execute("DELETE FROM chunk_embeddings")
                elif damage == "fts":
                    connection.execute("DELETE FROM chunk_fts")
                else:
                    connection.execute("UPDATE reindex_metadata SET document_count=999")
        finally:
            connection.close()
    monkeypatch.setattr(indexer, "normalize_candidate", corrupt)
    with pytest.raises(Exception):
        indexer.rebuild()
    assert fingerprint(active) == before


def test_report_failure_after_commit(pipeline, monkeypatch, capsys):
    active, _, _ = pipeline
    original = indexer.json.dumps
    def broken_end(value, **kwargs):
        if isinstance(value, dict) and value.get("event") == "reindex_end":
            raise OSError("fixture-secret")
        return original(value, **kwargs)
    monkeypatch.setattr(indexer.json, "dumps", broken_end)
    assert indexer.main() == 1
    output = capsys.readouterr()
    assert "published; report_failed" in output.err
    assert "fixture-secret" not in output.out + output.err
    with ActiveIndex(active):
        pass


def test_cli_safe_report_and_post_commit_cleanup(pipeline, monkeypatch, capsys):
    active, _, _ = pipeline
    def fail_cleanup(*args, **kwargs):
        raise OSError("fixture-secret")
    monkeypatch.setattr(indexer.shutil, "rmtree", fail_cleanup)
    assert indexer.main() == 0
    output = capsys.readouterr()
    assert '"published": true' in output.out and '"cleanup_warning": true' in output.out
    assert "fixture-secret" not in output.out + output.err
    with ActiveIndex(active):
        pass
    monkeypatch.setattr(indexer, "rebuild", fail_cleanup)
    assert indexer.main() == 1
    output = capsys.readouterr()
    assert "fixture-secret" not in output.out + output.err
    assert "Traceback" not in output.err


@pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux flock")
def test_lock_subprocess_exit_and_kill(tmp_path):
    active = tmp_path / "index.db"
    code = """
import sys,time
from pathlib import Path
from app.indexer import builder_lock
with builder_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    time.sleep(60)
"""
    for kill in (False, True):
        process = subprocess.Popen([sys.executable, "-c", code, str(active)], stdout=subprocess.PIPE, text=True)
        try:
            assert process.stdout.readline().strip() == "locked"
            with pytest.raises(indexer.ReindexError, match="busy"):
                with indexer.builder_lock(active):
                    pass
        finally:
            process.kill() if kill else process.terminate()
            process.wait(timeout=5)
        with indexer.builder_lock(active):
            pass
