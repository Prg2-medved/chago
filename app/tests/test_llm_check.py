import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from app import llm_check
from app.main import app


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://llm:8080")
    monkeypatch.setenv("LLM_MODEL_NAME", "test-alias")
    monkeypatch.setenv("LLM_MAX_TOKENS", "128")
    opener = Mock()
    factory = Mock(return_value=opener)
    monkeypatch.setattr(llm_check, "build_opener", factory)
    return opener, factory


def reply(opener, body, status=200):
    stream = io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
    stream.status = status
    opener.open.return_value = stream


def test_health(transport, capsys):
    opener, factory = transport
    reply(opener, {"status": "ok"})
    assert llm_check.main(["health"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "ok"}
    assert factory.call_args.args[0].proxies == {}
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://llm:8080/health"
    assert request.get_method() == "GET"
    assert opener.open.call_args.kwargs["timeout"] == 5


@pytest.mark.parametrize("body,status", [
    ({"status": "loading"}, 200), ({}, 200), ([], 200),
    (b"bad json", 200), ({"status": "ok"}, 201),
])
def test_bad_health(transport, body, status, capsys):
    reply(transport[0], body, status)
    assert llm_check.main(["health"]) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("command", ["health", "completion"])
@pytest.mark.parametrize("error", [
    HTTPError("http://llm/health", 503, "loading", {}, None),
    HTTPError("http://llm/health", 500, "error", {}, None),
    URLError("refused"), TimeoutError("timed out"),
])
def test_transport_errors(transport, command, error, capsys):
    transport[0].open.side_effect = error
    assert llm_check.main([command]) == 1
    assert capsys.readouterr().err
    assert transport[0].open.call_count == 1


def test_completion_alias_and_body(transport, capsys):
    opener, _ = transport
    reply(opener, {
        "model": "test-alias", "choices": [{"message": {"content": "Зимой холодно."}}],
        "timings": {"predicted_n": 4, "predicted_ms": 1000},
    })
    assert llm_check.main(["completion"]) == 0
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://llm:8080/v1/chat/completions"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {
        "model": "test-alias", "messages": [{"role": "user", "content": llm_check.QUESTION}],
        "stream": False, "max_tokens": 128, "temperature": 0.2, "top_p": 0.8, "top_k": 20,
    }
    assert opener.open.call_args.kwargs["timeout"] == 300
    output = json.loads(capsys.readouterr().out)
    assert output["answer"] == "Зимой холодно."
    assert output["timings"]["predicted_ms"] == 1000


@pytest.mark.parametrize("body", [
    {}, [], b"invalid", {"choices": []},
    {"model": "test-alias", "choices": [{"message": {"content": " "}}]},
    {"model": "file.gguf", "choices": [{"message": {"content": "Ответ"}}]},
    {"model": "test-alias", "choices": [{"message": {"content": None}}]},
])
def test_bad_completion(transport, body, capsys):
    reply(transport[0], body)
    assert llm_check.main(["completion"]) == 1
    assert capsys.readouterr().err
    assert transport[0].open.call_count == 1


@pytest.mark.parametrize("url", ["", "file:///model", "http://llm:8080/v1", "http://u:p@llm"])
def test_invalid_base_url(transport, monkeypatch, url):
    monkeypatch.setenv("LLM_BASE_URL", url)
    assert llm_check.main(["health"]) == 1
    transport[0].open.assert_not_called()


def test_bootstrap_health_does_not_call_llm(transport):
    transport[0].open.side_effect = AssertionError("LLM must not be called")
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/docs").status_code == 404
    transport[0].open.assert_not_called()
