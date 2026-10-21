from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from app.config import ChatSettings, load_chat_settings, load_settings
from app.main import app


@pytest.fixture(autouse=True)
def clear_chat_environment(monkeypatch):
    for suffix in ("BASE_URL", "MODEL_NAME", "MAX_TOKENS", "CONTEXT_SIZE", "TIMEOUT_SECONDS"):
        monkeypatch.delenv("LLM_" + suffix, raising=False)


def test_defaults_and_overrides(monkeypatch):
    settings = load_chat_settings()
    assert settings == ChatSettings()
    assert (settings.model_name, settings.max_tokens) == ("Qwen3-4B-Instruct-2507", 768)
    assert (settings.context_size, settings.timeout_seconds) == (8192, 300)
    assert (settings.temperature, settings.top_p, settings.top_k) == (0.2, 0.8, 20)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8081/")
    monkeypatch.setenv("LLM_MODEL_NAME", "custom-alias")
    monkeypatch.setenv("LLM_MAX_TOKENS", "128")
    monkeypatch.setenv("LLM_CONTEXT_SIZE", "1024")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    configured = load_chat_settings()
    assert configured == replace(settings, base_url="http://localhost:8081", model_name="custom-alias",
                                 max_tokens=128, context_size=1024, timeout_seconds=45)
    assert configured.max_tokens == load_settings().llm_max_tokens
    assert configured.model_name == load_settings().llm_model_name


@pytest.mark.parametrize("name", ["MAX_TOKENS", "CONTEXT_SIZE", "TIMEOUT_SECONDS"])
@pytest.mark.parametrize("value", ["", " ", "0", "-1", "1.5", "NaN", "inf", "true", "1_000", "+10", " 10", "SECRET"])
def test_invalid_environment_integers_are_safe(monkeypatch, name, value):
    monkeypatch.setenv("LLM_" + name, value)
    with pytest.raises(ValueError) as caught:
        load_chat_settings()
    assert str(caught.value) == "configuration: LLM_" + name


@pytest.mark.parametrize("name", ["max_tokens", "context_size", "timeout_seconds"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, float("inf"), float("nan"), "10"])
def test_invalid_typed_integers(name, value):
    with pytest.raises(ValueError, match="^configuration: chat_" + name + "$"):
        ChatSettings(**{name: value})


@pytest.mark.parametrize("reserve,window", [(768, 768), (769, 768), (1, 1)])
def test_reserve_must_be_smaller_than_window(monkeypatch, reserve, window):
    monkeypatch.setenv("LLM_MAX_TOKENS", str(reserve))
    monkeypatch.setenv("LLM_CONTEXT_SIZE", str(window))
    with pytest.raises(ValueError, match="^configuration: chat_token_reserve$"):
        load_chat_settings()
    with pytest.raises(ValueError, match="chat_token_reserve"):
        ChatSettings(max_tokens=reserve, context_size=window)


def test_smallest_budget_and_timeout(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "1")
    monkeypatch.setenv("LLM_CONTEXT_SIZE", "2")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1")
    settings = load_chat_settings()
    assert (settings.max_tokens, settings.context_size, settings.timeout_seconds) == (1, 2, 1)


def test_invalid_chat_settings_do_not_break_app_only(monkeypatch, tmp_path):
    path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("INDEX_PATH", str(path))
    monkeypatch.setenv("LLM_CONTEXT_SIZE", "invalid")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "invalid")
    assert load_settings().port == 8000
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
    assert not path.exists()
