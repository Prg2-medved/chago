from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from app import indexer
from app.index_state import load_index_state
from app.main import app
from test_indexer import pipeline


@pytest.mark.parametrize("kind", ["missing", "corrupt", "legacy", "version", "counts"])
def test_unavailable(pipeline, kind):
    active, _, _ = pipeline
    if kind == "corrupt":
        active.write_bytes(b"corrupt")
    elif kind != "missing":
        indexer.rebuild()
        connection = sqlite3.connect(active)
        try:
            with connection:
                if kind == "legacy":
                    connection.execute("DROP TABLE reindex_metadata")
                elif kind == "version":
                    connection.execute("PRAGMA user_version=99")
                else:
                    connection.execute("UPDATE reindex_metadata SET chunk_count=999")
        finally:
            connection.close()
    before = active.read_bytes() if active.exists() else None
    state = load_index_state(active)
    assert not state.available and state.index is None and state.reason
    state.close()
    assert (active.read_bytes() if active.exists() else None) == before
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert not app.state.index.available


def test_lifecycle_generations_and_handles(pipeline, monkeypatch):
    active, rows, _ = pipeline
    indexer.rebuild()
    with TestClient(app):
        first = app.state.index.index
        assert first.snapshot.documents[0].markdown == rows[0]["markdown"]
    assert first._reader._connection is None
    rows[0]["markdown"] = "Second generation"
    indexer.rebuild()
    with TestClient(app):
        second = app.state.index.index
        assert second.snapshot.documents[0].markdown == "Second generation"
    before = active.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("source unavailable")
    monkeypatch.setattr(indexer.ingestion, "ingest", fail)
    with pytest.raises(OSError):
        indexer.rebuild()
    assert active.read_bytes() == before
    with TestClient(app):
        assert app.state.index.index.metadata == second.metadata
    rows.clear()


def test_load_without_source_or_model_dependencies(pipeline):
    active, _, _ = pipeline
    indexer.rebuild()
    code = """
import sys
for module in ('torch','sentence_transformers','transformers','tokenizers'):
    sys.modules[module] = None
from pathlib import Path
from app.index_state import load_index_state
state = load_index_state(Path(sys.argv[1]))
assert state.available
state.close()
"""
    result = subprocess.run([sys.executable, "-c", code, str(active)], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
