import asyncio
import os
import threading

from fastapi.testclient import TestClient
import pytest

from app import indexer
from app.config import RetrievalSettings
from app.embeddings import EmbeddingError
from app.hybrid_retrieval import HybridIndex, HybridRetrievalError
from app.index_state import ActiveIndex, RetrievalService
from app.main import app
from app.retrieval import RetrievalError
from test_indexer import Encoder, pipeline


def test_borrowed_view_identity_ownership_and_provenance(pipeline, monkeypatch):
    path, _, assets = pipeline
    indexer.rebuild()
    encoder = Encoder(indexer.load_embedding_settings())
    with HybridIndex(path, encoder) as standalone:
        expected = standalone.search("Heading")
    with ActiveIndex(path) as active:
        def no_reopen(*args):
            pytest.fail("active pathname reopened")
        monkeypatch.setattr("app.hybrid_retrieval.LexicalReader", no_reopen)
        with HybridIndex._from_active(active, encoder, RetrievalSettings()) as view:
            assert view.search("Heading") == expected
            assert view._semantic.matrix is active.matrix
            assert view.snapshot is active.snapshot
            assert view._semantic.chunks == tuple(sorted(active.snapshot.chunks, key=lambda c: c.chunk_id))
            assert view.settings == RetrievalSettings(10, 10, 60, 6)
        assert active._reader._connection is not None
        bad = Encoder(indexer.load_embedding_settings())
        bad.identity = {**encoder.identity, "revision": "other"}
        with pytest.raises(RetrievalError, match="retrieval_identity_rebuild"):
            HybridIndex._from_active(active, bad, RetrievalSettings())
        assert active._reader._connection is not None
        with HybridIndex._from_active(active, encoder, RetrievalSettings()) as view:
            assert view.search("Heading") == expected


def test_worker_concurrent_searches_and_single_close(pipeline, monkeypatch):
    path, _, _ = pipeline
    indexer.rebuild()
    threads = []
    created = []
    original_close = ActiveIndex.close
    closed = []
    def create(settings):
        threads.append(threading.get_ident())
        created.append(settings)
        encoder = Encoder(settings)
        original = encoder.encode_query
        def encode(question):
            threads.append(threading.get_ident())
            return original(question)
        encoder.encode_query = encode
        return encoder
    def close(active):
        threads.append(threading.get_ident())
        closed.append(active)
        original_close(active)
    monkeypatch.setattr("app.index_state.LocalEncoder", create)
    monkeypatch.setattr(ActiveIndex, "close", close)
    async def run():
        service = RetrievalService(path)
        await service.start()
        assert not created
        main_thread = threading.get_ident()
        active = service.state.index
        results = await asyncio.gather(*(service.search("Heading") for _ in range(8)))
        assert results[0] and all(result == results[0] for result in results)
        await service.close()
        await service.close()
        assert closed == [active]
        assert active._reader._connection is None
        assert len(created) == 1
        assert len(set(threads)) == 1 and threads[0] != main_thread
        with pytest.raises(HybridRetrievalError, match="retrieval_lifecycle"):
            await service.search("closed")
    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_search_error_or_cancellation_drains_before_shutdown(pipeline, monkeypatch, cancel):
    path, _, _ = pipeline
    indexer.rebuild()
    entered, release = threading.Event(), threading.Event()
    def create(settings):
        encoder = Encoder(settings)
        def encode(question):
            entered.set()
            assert release.wait(5)
            if not cancel:
                raise EmbeddingError("embedding_query")
            return Encoder(settings).encode_query(question)
        encoder.encode_query = encode
        return encoder
    monkeypatch.setattr("app.index_state.LocalEncoder", create)
    async def run():
        service = RetrievalService(path)
        await service.start()
        active = service.state.index
        task = asyncio.create_task(service.search("Heading"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            closing = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            assert not closing.done()
            assert active._reader._connection is not None
        finally:
            release.set()
        if not cancel:
            with pytest.raises(EmbeddingError, match="embedding_query"):
                await task
        await closing
        assert active._reader._connection is None
    asyncio.run(run())


def test_snapshot_search_after_path_replacement(pipeline, monkeypatch, tmp_path):
    path, rows, _ = pipeline
    indexer.rebuild()
    before = path.read_bytes()
    monkeypatch.setattr("app.index_state.LocalEncoder", Encoder)
    replacement = tmp_path / "replacement.sqlite3"
    async def run():
        replaced_while_open = False
        service = RetrievalService(path)
        await service.start()
        try:
            original = await service.search("Heading")
            rows[0].update(markdown="# New heading\nReplacement text", title="New title", path="new-path")
            monkeypatch.setenv("INDEX_PATH", str(replacement))
            await asyncio.to_thread(indexer.rebuild)
            # Windows may deny replacing open SQLite files. Explicitly preserve
            # that platform limitation; POSIX must exercise actual replacement.
            try:
                os.replace(replacement, path)
            except PermissionError:
                if os.name != "nt":
                    raise
                assert path.read_bytes() == before
            else:
                assert path.read_bytes() != before
                replaced_while_open = True
            def no_reopen(*args):
                pytest.fail("active pathname reopened during search")
            monkeypatch.setattr("app.hybrid_retrieval.LexicalReader", no_reopen)
            assert await service.search("Heading") == original
            for result in original:
                chunk = result.chunk
                assert chunk.document.title == "Title"
                assert "new-path" not in chunk.document.source_url
                assert chunk.document.markdown == service.state.index.snapshot.documents[0].markdown
                assert all(chunk.document.markdown[start:end] for start, end in chunk.source_ranges)
        finally:
            await service.close()
        if replacement.exists():
            os.replace(replacement, path)
        newer = RetrievalService(path)
        await newer.start()
        try:
            assert newer.state.index.snapshot.documents[0].title == "New title"
        finally:
            await newer.close()
        if replaced_while_open:
            print("PATHNAME_REPLACEMENT_OK: old snapshot retained; restart loaded new generation")
    asyncio.run(run())


def test_app_only_missing_index_and_assets(tmp_path, monkeypatch):
    path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("INDEX_PATH", str(path))
    monkeypatch.setenv("EMBEDDING_MODEL_PATH", str(tmp_path / "missing-model"))
    def unexpected(*args):
        pytest.fail("encoder loaded at startup")
    monkeypatch.setattr("app.index_state.LocalEncoder", unexpected)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert not app.state.index.available
        with pytest.raises(HybridRetrievalError, match="index_unavailable"):
            client.portal.call(app.state.retrieval.search, "Heading")
    assert not path.exists()


def test_encoder_assets_failure_preserves_health_and_reader(pipeline, monkeypatch):
    path, _, _ = pipeline
    indexer.rebuild()
    def missing(settings):
        raise EmbeddingError("embedding_assets")
    monkeypatch.setattr("app.index_state.LocalEncoder", missing)
    with TestClient(app) as client:
        active = app.state.index.index
        with pytest.raises(EmbeddingError, match="embedding_assets"):
            client.portal.call(app.state.retrieval.search, "Heading")
        assert client.get("/health").json() == {"status": "ok"}
        assert active._reader._connection is not None
    assert active._reader._connection is None
