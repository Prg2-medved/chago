import asyncio
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from time import monotonic, sleep

from fastapi.testclient import TestClient
import httpx
import pytest

from app import indexer
from app.health import HealthProbe, index_snapshot, probe
from app.main import app, lifespan
from test_indexer import pipeline


@pytest.fixture
def endpoint():
    state = {"status": 200, "body": b'{"status":"ok"}', "delay": 0, "calls": []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["calls"].append(self.path)
            sleep(state["delay"])
            try:
                self.send_response(state["status"])
                self.send_header("Location", "/redirected")
                self.send_header("Content-Length", str(len(state["body"])))
                self.end_headers()
                self.wfile.write(state["body"])
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_health(endpoint, tmp_path, monkeypatch):
    origin, state = endpoint
    monkeypatch.setenv("LLM_BASE_URL", origin)
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "missing"))
    monkeypatch.setattr("app.index_state.LocalEncoder", lambda *args: pytest.fail("encoder loaded"))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "ok", "app": {"status": "ok"},
        "index": {"status": "missing", "available": False, "pages": None, "chunks": None, "indexed_at": None},
        "llm": {"status": "ok"}, "chat": {"status": "available"}}
    assert state["calls"] == ["/health"]


@pytest.mark.parametrize("empty", [False, True])
def test_metadata_in_memory_without_encoder_or_sqlite(pipeline, monkeypatch, empty):
    _, rows, _ = pipeline
    if empty:
        rows.clear()
    indexer.rebuild()
    monkeypatch.setenv("LLM_BASE_URL", "invalid-secret")
    monkeypatch.setattr("app.index_state.LocalEncoder", lambda *args: pytest.fail("encoder loaded"))
    with TestClient(app) as client:
        metadata = app.state.index.index.metadata
        expected = {"status": "ok", "available": True, "pages": metadata.document_count,
                    "chunks": metadata.chunk_count, "indexed_at": metadata.indexed_at}
        assert client.get("/health").json()["index"] == expected
        assert asdict(index_snapshot(app.state.index)) == expected
        assert expected["pages"] == (0 if empty else 1)
        assert (expected["chunks"] == 0) if empty else (expected["chunks"] > 0)


@pytest.mark.parametrize("status,body,expected", [
    (200, b'{"status":"ok"}', "ok"), (503, b"SECRET", "unavailable"),
    (302, b"SECRET", "invalid_response"), (200, b"{SECRET", "invalid_response"),
    (200, b"[]", "invalid_response"), (200, b'{"status":"loading"}', "invalid_response"),
    (200, b" " * 65537, "invalid_response"),
    (200, b'{"status":"ok"}' + b" " * (65536 - 15), "ok"),
], ids=["ok", "loading", "redirect", "broken-json", "array", "wrong-status", "oversize", "body-limit"])
def test_transport(endpoint, monkeypatch, status, body, expected):
    origin, state = endpoint
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    state.update(status=status, body=body)
    assert probe(origin) == expected
    assert state["calls"] == ["/health"]


@pytest.mark.parametrize("origin", ["", "http://user:SECRET@host", "http://host/v1", "http://host?q=SECRET",
    "http://host#SECRET", "file:///tmp/SECRET", "http://host:99999", "http://host:0", "http://host:",
    "http://host\\SECRET", "http://host\nSECRET"])
def test_configuration(origin):
    assert probe(origin) == "configuration_error"


def test_timeout_is_bounded(endpoint):
    origin, state = endpoint
    state["delay"] = 5.2
    started = monotonic()
    assert probe(origin) == "timeout"
    assert monotonic() - started < 5.5
    assert state["calls"] == ["/health"]


def test_shared_probe_cancellation_and_shutdown(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(origin):
        calls.append(origin)
        entered.set()
        assert release.wait(5)
        return "ok"
    monkeypatch.setattr("app.health.probe", slow)
    async def run():
        coordinator = HealthProbe("origin")
        try:
            first = asyncio.create_task(coordinator.check())
            assert await asyncio.to_thread(entered.wait, 2)
            others = [asyncio.create_task(coordinator.check()) for _ in range(12)]
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await asyncio.sleep(.02)
            assert len(calls) == 1 and all(not task.done() for task in others)
            started = monotonic()
            coordinator.close()
            assert monotonic() - started < .2
            release.set()
            assert await asyncio.gather(*others) == ["ok"] * 12
            assert await coordinator.check() == "unavailable"
        finally:
            release.set()
            coordinator.close()
    asyncio.run(run())


def test_parallel_http_health_shares_probe_after_client_cancellation(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(origin):
        calls.append(origin)
        entered.set()
        assert release.wait(5)
        return "ok"
    monkeypatch.setattr("app.health.probe", slow)
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "missing"))
    async def run():
        async with lifespan(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                first = asyncio.create_task(client.get("/health"))
                assert await asyncio.to_thread(entered.wait, 2)
                others = [asyncio.create_task(client.get("/health")) for _ in range(8)]
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
                await asyncio.sleep(.03)
                assert len(calls) == 1
                app.state.chat.gate.generation_uncertain = True
                release.set()
                responses = await asyncio.gather(*others)
                assert all(response.json()["llm"]["status"] == "ok" for response in responses)
                assert all(response.json()["chat"]["status"] == "generation_uncertain" for response in responses)
    try:
        asyncio.run(run())
    finally:
        release.set()
