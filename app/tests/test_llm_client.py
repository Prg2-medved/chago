from collections import deque
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import pytest

from app.config import ChatSettings
from app.llm_client import LLMClient, LLMError


@pytest.fixture
def http_llm():
    calls, replies = [], deque()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, payload))
            status, body, delay = replies.popleft()
            if delay:
                time.sleep(delay)
            if status == 0:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            try:
                self.send_response(status)
                self.send_header("Location", "http://127.0.0.1:1/private")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = ChatSettings(base_url=f"http://127.0.0.1:{server.server_port}", model_name="alias", timeout_seconds=1)
    try:
        yield LLMClient(settings), calls, replies
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


MESSAGES = [{"role": "system", "content": "Правила"}, {"role": "user", "content": "Вопрос 🧪"}]


def envelope(content="answer"):
    return {"model": "alias", "choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 9}}


def test_payload_token_path_and_no_proxy(http_llm, monkeypatch):
    client, calls, replies = http_llm
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    replies.extend([(200, {"prompt": "FULL TEMPLATE<assistant>"}, 0), (200, {"tokens": [1, 2, 3]}, 0),
                    (200, envelope(), 0)])
    assert client.count_prompt(MESSAGES) == 3
    assert client.complete(MESSAGES).content == "answer"
    assert calls == [
        ("/apply-template", {"messages": MESSAGES, "add_generation_prompt": True}),
        ("/tokenize", {"content": "FULL TEMPLATE<assistant>", "add_special": True, "parse_special": True, "with_pieces": False}),
        ("/v1/chat/completions", {"model": "alias", "messages": MESSAGES, "stream": False,
          "max_tokens": 768, "temperature": 0.2, "top_p": 0.8, "top_k": 20, "cache_prompt": False}),
    ]


@pytest.mark.parametrize("body", [b"{SECRET", [], {}, {"model": "other", "choices": [{"message": {"content": "secret"}}]},
                                      envelope(""), envelope("  "), envelope(None), {"model": "alias", "choices": []}])
def test_completion_protocol_no_retry(http_llm, body):
    client, calls, replies = http_llm
    replies.append((200, body, 0))
    with pytest.raises(LLMError) as caught:
        client.complete(MESSAGES)
    assert caught.value.status == 502 and not caught.value.generation_uncertain
    assert "SECRET" not in str(caught.value) and len(calls) == 1


@pytest.mark.parametrize("status,expected", [(503, 503), (500, 503), (400, 502), (302, 502), (307, 502)])
def test_rejection_and_redirects(http_llm, status, expected):
    client, calls, replies = http_llm
    replies.append((status, {"secret": "private"}, 0))
    with pytest.raises(LLMError) as caught:
        client.complete(MESSAGES)
    assert caught.value.status == expected and not caught.value.generation_uncertain
    assert len(calls) == 1


@pytest.mark.parametrize("completion", [True, False])
@pytest.mark.parametrize("disconnect", [True, False])
def test_timeout_or_socket_loss_uncertainty(http_llm, completion, disconnect):
    client, calls, replies = http_llm
    replies.append((0 if disconnect else 200, envelope(), 0 if disconnect else 1.2))
    with pytest.raises(LLMError) as caught:
        (client.complete if completion else client.count_prompt)(MESSAGES)
    assert caught.value.status == (503 if disconnect else 504)
    assert caught.value.generation_uncertain == completion
    assert len(calls) == 1


def test_refused_connection_is_before_send():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
        client = LLMClient(ChatSettings(base_url=f"http://127.0.0.1:{port}"))
        with pytest.raises(LLMError) as caught:
            client.complete(MESSAGES)
    assert caught.value.status == 503 and not caught.value.generation_uncertain


@pytest.mark.parametrize("prompt", [None, "", 5])
def test_invalid_template(http_llm, prompt):
    client, calls, replies = http_llm
    replies.append((200, {"prompt": prompt}, 0))
    with pytest.raises(LLMError, match="llm_template_protocol"):
        client.count_prompt(MESSAGES)
    assert len(calls) == 1


@pytest.mark.parametrize("tokens", [None, [], [True], ["1"], [{"id": 1}], [1.5]])
def test_invalid_tokens(http_llm, tokens):
    client, calls, replies = http_llm
    replies.extend([(200, {"prompt": "prefix 🧪"}, 0), (200, {"tokens": tokens}, 0)])
    with pytest.raises(LLMError, match="llm_token_protocol"):
        client.count_prompt(MESSAGES)
    assert len(calls) == 2


def test_exact_budget_boundary(http_llm):
    client, calls, replies = http_llm
    assert client.fits(8192 - 768)
    assert not client.fits(8192 - 768 + 1)
    replies.extend([(200, {"prompt": "a"}, 0), (200, {"tokens": list(range(7500))}, 0)])
    assert client.count_prompt(MESSAGES) == 7500
    assert not client.fits(7500)  # No character-based estimate for the one-letter template.


@pytest.mark.parametrize("url", ["http://user:SECRET@host", "http://host/v1", "http://host?q=SECRET",
                                      "file:///tmp/model", "http://host:99999", "http://host\\other", ""])
def test_invalid_origin_before_transport(url):
    with pytest.raises(LLMError, match="^llm_configuration$"):
        LLMClient(replace(ChatSettings(), base_url=url))
