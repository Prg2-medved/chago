import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from time import monotonic
from types import SimpleNamespace

import httpx
import pytest

from app.chat import ChatError, ChatService
from app.config import ChatSettings
from app.grounding import FALLBACK
from app.hybrid_retrieval import HybridResult
from app.llm_client import LLMError
from app.main import app, lifespan
from test_grounding import chunk, generated, marker


class Retrieval:
    async def search(self, question):
        return (HybridResult(1, 1.0, chunk(), 1, 1.0, 1, -1, ()),)


@pytest.fixture
def barrier_llm(monkeypatch):
    state = SimpleNamespace(entered=threading.Event(), release=threading.Event(),
                            completions=0, active=0, max_active=0, token_failure=False)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status = 200
            if self.path == "/apply-template":
                result = {"prompt": "template<assistant>"}
            elif self.path == "/tokenize":
                status = 503 if state.token_failure else 200
                result = {"tokens": [1, 2, 3]}
            else:
                state.completions += 1
                state.active += 1
                state.max_active = max(state.max_active, state.active)
                state.entered.set()
                try:
                    if not state.release.wait(8):
                        raise RuntimeError("test barrier not released")
                finally:
                    state.active -= 1
                result = {"model": "alias", "choices": [{"message": {"content": generated("Answer " + marker())}}]}
            raw = json.dumps(result).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.settings = ChatSettings(base_url=f"http://127.0.0.1:{server.server_port}", model_name="alias", timeout_seconds=1)
    monkeypatch.setattr("app.chat.load_chat_settings", lambda: state.settings)
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join()


async def entered(state):
    assert await asyncio.to_thread(state.entered.wait, 3)


def test_two_requests_are_serialized_and_wait_is_measured(barrier_llm, caplog):
    state = barrier_llm
    caplog.set_level("INFO", logger="app.chat")
    async def run():
        service = ChatService(Retrieval())
        try:
            first = asyncio.create_task(service.answer("first"))
            await entered(state)
            second = asyncio.create_task(service.answer("second"))
            await asyncio.sleep(.03)
            assert state.completions == 1 and not second.done()
            state.release.set()
            answers = await asyncio.gather(first, second)
            assert all(answer.answer == "Answer [1]" for answer in answers)
            assert state.completions == 2 and state.max_active == 1
        finally:
            state.release.set()
            await service.close()
    asyncio.run(run())
    assert "wait_ms=" in caplog.text


@pytest.mark.parametrize("cancel_first", [False, True])
def test_timeout_keeps_server_active_blocks_waiters_and_new_http(barrier_llm, tmp_path, monkeypatch, cancel_first):
    state = barrier_llm
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "missing.db"))
    async def run():
        async with lifespan(app):
            app.state.chat.retrieval = Retrieval()
            gate = app.state.chat.gate
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                def post(question):
                    return client.post("/api/chat", json={"session_id": "s", "message": question})
                first = asyncio.create_task(post("first"))
                await entered(state)
                second = asyncio.create_task(post("second"))
                if cancel_first:
                    first.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await first
                else:
                    assert (await first).status_code == 504
                assert (await asyncio.wait_for(second, 3)).status_code == 503
                assert state.active == 1  # The fake server is still generating after HTTP timeout.
                assert gate.generation_uncertain and gate._semaphore.locked()
                assert (await client.get("/health")).json() == {"status": "ok"}
                assert (await post("new")).status_code == 503
                await asyncio.sleep(.03)
                state.release.set()  # Even eventual server end does not authorize an automatic release.
                assert (await client.get("/health")).json() == {"status": "ok"}
                assert (await post("later")).status_code == 503
                assert state.completions == 1
    asyncio.run(run())


def test_cancellation_waits_for_late_full_response_before_release(barrier_llm):
    state = barrier_llm
    async def run():
        service = ChatService(Retrieval())
        try:
            first = asyncio.create_task(service.answer("first"))
            await entered(state)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(service.answer("second"))
            await asyncio.sleep(.03)
            assert state.completions == 1 and not second.done()
            state.release.set()
            assert (await second).answer == "Answer [1]"
            assert state.completions == 2 and not service.gate.generation_uncertain
        finally:
            state.release.set()
            await service.close()
    asyncio.run(run())


def test_cancelled_waiter_never_sends_a_completion(barrier_llm):
    state = barrier_llm
    async def run():
        service = ChatService(Retrieval())
        try:
            first = asyncio.create_task(service.answer("first"))
            await entered(state)
            waiting = asyncio.create_task(service.answer("waiting"))
            await asyncio.sleep(.01)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            state.release.set()
            await first
            assert (await service.answer("third")).answer == "Answer [1]"
            assert state.completions == 2
        finally:
            state.release.set()
            await service.close()
    asyncio.run(run())


def test_token_errors_and_pre_send_errors_release_slot(barrier_llm, monkeypatch):
    state = barrier_llm
    async def run():
        service = ChatService(Retrieval())
        try:
            state.token_failure = True
            with pytest.raises(ChatError) as caught:
                await service.answer("token unavailable")
            assert caught.value.status == 503
            assert not service.gate.generation_uncertain
            assert not service.gate._semaphore.locked() and state.completions == 0
            state.token_failure = False
            with monkeypatch.context() as patch:
                def unavailable(settings):
                    raise LLMError("llm_configuration", 503)
                patch.setattr("app.chat.LLMClient", unavailable)
                with pytest.raises(ChatError):
                    await service.answer("before send")
            assert not service.gate._semaphore.locked()
            state.release.set()
            assert (await service.answer("recovered")).answer == "Answer [1]"
        finally:
            state.release.set()
            await service.close()
    asyncio.run(run())


def test_shutdown_is_bounded_without_claiming_remote_end(barrier_llm):
    state = barrier_llm
    async def run():
        service = ChatService(Retrieval())
        first = asyncio.create_task(service.answer("first"))
        await entered(state)
        started = monotonic()
        await service.gate.close(grace_seconds=.02)
        assert monotonic() - started < .5 and state.active == 1
        with pytest.raises(ChatError) as caught:
            await service.answer("after shutdown")
        assert caught.value.status == 503
        state.release.set()
        await first
    asyncio.run(run())
