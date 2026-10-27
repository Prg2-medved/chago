from dataclasses import replace
import json
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from app.chat import ChatError
from app import indexer
from app.config import ChatSettings
from app.embeddings import EmbeddingError
from app.grounding import FALLBACK, REFUSAL
from app.hybrid_retrieval import HybridResult
from app.llm_client import Completion, LLMClient, LLMError
from app.main import app
from test_grounding import chunk, generated, marker
from test_embeddings import fake_encoder
from test_llm_client import http_llm
from test_indexer import pipeline


class FakeClient:
    def __init__(self):
        self.messages = []
        self.content = generated("Подтверждённый ответ " + marker())
        self.count = 100
        self.limit = 8192
        self.failure = None

    def count_prompt(self, messages):
        if self.failure and self.failure[0] == "count":
            raise self.failure[1]
        return self.count

    def fits(self, count):
        return count + 768 <= self.limit

    def complete(self, messages):
        self.messages.append(messages)
        if self.failure and self.failure[0] == "complete":
            raise self.failure[1]
        return Completion(self.content, self.count)


@pytest.fixture
def chat_api(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "missing.db"))
    fake, queries = FakeClient(), []
    results = [HybridResult(1, 1.0, chunk(), 1, 1.0, 1, -1, ())]
    async def search(question):
        queries.append(question)
        return tuple(results)
    monkeypatch.setattr("app.chat.LLMClient", lambda settings: fake)
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.retrieval, "search", search)
        yield client, fake, queries, results


def send(client, message="question", session="session"):
    return client.post("/api/chat", json={"session_id": session, "message": message})


def test_contract_and_no_session_history_or_public_override(chat_api):
    client, fake, queries, _ = chat_api
    first = send(client).json()
    assert first == {"answer": "Подтверждённый ответ [1]", "insufficient_context": False, "sources": [
        {"title": "Title", "heading": "Heading", "url": "https://wiki.example/ru/page", "quote": "source command"}]}
    assert send(client, "second question").status_code == 200
    assert queries == ["question", "second question"]
    assert len(fake.messages) == 2 and len(fake.messages[-1]) == 2
    assert json.loads(fake.messages[-1][1]["content"])["question"] == "second question"
    for path in ("/api/reindex", "/reindex"):
        assert client.post(path).status_code == 404
    response = client.post("/api/chat", json={"session_id": "s", "message": "q", "context": "SECRET"})
    assert response.status_code == 422 and "SECRET" not in response.text
    assert len(queries) == 2


def test_unfenced_command_uses_shared_fallback_without_retry_or_sensitive_logs(chat_api, caplog):
    client, fake, queries, results = chat_api
    original = "```sh\nnebula-tool --local\n```"
    results[0] = replace(results[0], chunk=chunk(original))
    fake.content = generated("PRIVATE_GENERATION nebula-tool --remote " + marker())
    response = send(client, "PRIVATE_MESSAGE", "PRIVATE_SESSION")
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == FALLBACK and body["insufficient_context"]
    assert body["sources"][0]["quote"] == original
    assert queries == ["PRIVATE_MESSAGE"] and len(fake.messages) == 1
    assert "PRIVATE" not in caplog.text and "--remote" not in caplog.text
    assert "query_ms=" in caplog.text and "generation_ms=" in caplog.text
    fake.content = generated("Сервис готов. " + marker())
    assert send(client, "Обычный вопрос").json()["insufficient_context"] is False
    assert len(fake.messages) == 2


@pytest.mark.parametrize("field,limit", [("session_id", 128), ("message", 4096)])
@pytest.mark.parametrize("value", ["x", "🧪", "ё", " "])
def test_original_unicode_length_boundaries(chat_api, field, limit, value):
    client, fake, queries, _ = chat_api
    # Whitespace counts before trim; keep a nonblank character.
    exact = "x" + value * (limit - 1)
    payload = {"session_id": "session", "message": "question", field: exact}
    assert client.post("/api/chat", json=payload).status_code == 200
    if field == "message":
        assert queries[-1] == exact.strip()
        assert json.loads(fake.messages[-1][1]["content"])["question"] == exact.strip()
    before = len(queries), len(fake.messages)
    payload[field] = exact + value
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 422 and "input" not in response.text
    assert (len(queries), len(fake.messages)) == before


@pytest.mark.parametrize("field", ["session_id", "message"])
@pytest.mark.parametrize("value", [None, 1, True, [], {}, "", " \t\n"])
def test_invalid_fields_no_retrieval_or_model(chat_api, field, value):
    client, fake, queries, _ = chat_api
    payload = {"session_id": "SECRET_SESSION", "message": "SECRET_MESSAGE", field: value}
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 422
    assert not queries and not fake.messages
    assert "SECRET" not in response.text
    payload.pop(field)
    assert client.post("/api/chat", json=payload).status_code == 422


def test_empty_retrieval_and_packed_context_without_completion(chat_api):
    client, fake, queries, results = chat_api
    results.clear()
    assert send(client).json() == {"answer": REFUSAL, "insufficient_context": True, "sources": []}
    assert queries == ["question"] and not fake.messages
    results.append(HybridResult(1, 1.0, chunk(), 1, 1.0, 1, -1, ()))
    fake.count_prompt = lambda messages: 5 if not json.loads(messages[1]["content"])["CONTEXT"] else 9000
    assert send(client).json()["answer"] == REFUSAL
    assert not fake.messages


def test_e5_and_llm_limits_separate(chat_api, monkeypatch, fake_encoder):
    client, fake, queries, results = chat_api
    async def overflow(question):
        fake_encoder.encode_query(question)
        return tuple(results)
    with monkeypatch.context() as patch:
        patch.setattr(app.state.retrieval, "search", overflow)
        assert send(client, "overflow").status_code == 422
    fake.count = 8192
    assert send(client, "short but LLM over limit").status_code == 422
    assert not fake.messages


@pytest.mark.parametrize("failure,status", [(LLMError("llm_unavailable", 503), 503),
    (LLMError("llm_timeout", 504, generation_uncertain=True), 504), (LLMError("llm_protocol", 502), 502)])
def test_llm_failures_are_technical(chat_api, failure, status):
    client, fake, _, _ = chat_api
    fake.failure = ("complete", failure)
    response = send(client)
    assert response.status_code == status and "insufficient_context" not in response.json()


@pytest.mark.parametrize("error", [EmbeddingError("embedding_assets"), RuntimeError("SECRET_DSN")])
def test_retrieval_failure_no_silent_fallback(chat_api, monkeypatch, error):
    client, fake, _, _ = chat_api
    async def fail(question):
        raise error
    monkeypatch.setattr(app.state.retrieval, "search", fail)
    response = send(client)
    assert response.status_code == 503 and not fake.messages
    assert "SECRET" not in response.text


def test_missing_index_is_503_and_health_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "missing.db"
    monkeypatch.setenv("INDEX_PATH", str(path))
    with TestClient(app) as client:
        assert send(client).status_code == 503
        assert client.get("/health").json() == {"status": "ok"}
    assert not path.exists()


@pytest.mark.parametrize("kind", ["corrupt", "incompatible", "missing_assets"])
def test_real_index_or_assets_failure_is_503(pipeline, kind, monkeypatch):
    path, _, assets = pipeline
    if kind == "corrupt":
        path.write_bytes(b"corrupt")
    else:
        indexer.rebuild()
        if kind == "incompatible":
            with sqlite3.connect(path) as connection:
                connection.execute("PRAGMA user_version=99")
    before = path.read_bytes()
    monkeypatch.setenv("EMBEDDING_MODEL_PATH", str(assets / "absent"))
    def unexpected(settings):
        pytest.fail("LLM must not be called on index/embedding failure")
    monkeypatch.setattr("app.chat.LLMClient", unexpected)
    with TestClient(app) as client:
        assert send(client).status_code == 503
        assert client.get("/health").json() == {"status": "ok"}
    assert path.read_bytes() == before


def test_malformed_generated_content_has_safe_200_fallback(chat_api):
    client, fake, _, _ = chat_api
    fake.content = "SECRET_UNSUPPORTED_ASSERTION"
    response = send(client)
    assert response.status_code == 200
    assert response.json()["answer"] == FALLBACK and response.json()["insufficient_context"]
    assert "SECRET" not in response.text and len(fake.messages) == 1


def test_logs_and_errors_do_not_contain_sensitive_text(chat_api, caplog, monkeypatch):
    client, fake, _, results = chat_api
    results[0] = replace(results[0], chunk=chunk("SECRET_SOURCE"))
    response = send(client, "SECRET_MESSAGE", "SECRET_SESSION")
    assert response.status_code == 200
    assert "query_ms=" in caplog.text and "retrieval_ms=" in caplog.text
    assert "wait_ms=" in caplog.text and "generation_ms=" in caplog.text
    fake.failure = ("count", RuntimeError("SECRET_PASSWORD"))
    response = send(client, "SECRET_MESSAGE", "SECRET_SESSION")
    assert response.status_code == 503
    assert "SECRET" not in caplog.text and "SECRET" not in response.text


def test_startup_emits_safe_info_to_stderr_in_fresh_process(tmp_path):
    # No pytest logging handler or inherited logger level in this process.
    script = '''
import logging
from logging.config import dictConfig
import sys
from unittest.mock import patch
from uvicorn.config import LOGGING_CONFIG
dictConfig(LOGGING_CONFIG)
sys.path.insert(0, "tests")
from test_chat_api import FakeClient, chunk, HybridResult, TestClient, app, send

assert logging.getLogger("app.chat").getEffectiveLevel() == logging.WARNING
fake = FakeClient()
async def search(question):
    return (HybridResult(1, 1.0, chunk("SECRET_SOURCE"), 1, 1.0, 1, -1, ()),)
with patch("app.main.load_index_path", return_value=sys.argv[1]), patch("app.chat.LLMClient", return_value=fake):
    for _ in range(2):
        with TestClient(app) as client:
            app.state.retrieval.search = search
            fake.failure = None
            assert send(client, "SECRET_MESSAGE", "SECRET_SESSION").status_code == 200
            fake.failure = ("count", RuntimeError("SECRET_PASSWORD_DSN"))
            assert send(client, "SECRET_MESSAGE", "SECRET_SESSION").status_code == 503
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path / "missing.db")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("INFO app.chat chat generation_ms=") == 2
    assert result.stderr.count("INFO app.chat chat outcome=ok query_ms=") == 2
    assert result.stderr.count("outcome=retrieval_or_configuration_unavailable query_ms=") == 2
    assert all(field in result.stderr for field in ("retrieval_ms=", "wait_ms=", "generation_ms="))
    assert "SECRET" not in result.stdout + result.stderr


def test_api_real_http_client_to_fake_server(chat_api, http_llm, monkeypatch):
    client, _, _, _ = chat_api
    llm, calls, replies = http_llm
    monkeypatch.setattr("app.chat.load_chat_settings", lambda: llm.settings)
    monkeypatch.setattr("app.chat.LLMClient", LLMClient)
    replies.extend([(200, {"prompt": "minimal"}, 0), (200, {"tokens": [1]}, 0),
                    (200, {"prompt": "full"}, 0), (200, {"tokens": [1, 2]}, 0),
                    (200, {"model": "alias", "choices": [{"message": {"content": generated("Answer " + marker())}}]}, 0)])
    assert send(client).json()["answer"] == "Answer [1]"
    assert [path for path, _ in calls] == ["/apply-template", "/tokenize", "/apply-template", "/tokenize", "/v1/chat/completions"]
