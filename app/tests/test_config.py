import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.config import load_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)
    settings = load_settings()
    assert (settings.host, settings.port) == ("127.0.0.1", 8000)


def test_overrides(monkeypatch):
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "8010")
    settings = load_settings()
    assert (settings.host, settings.port) == ("0.0.0.0", 8010)


@pytest.mark.parametrize("port", ["1", "65535"])
def test_port_boundaries(monkeypatch, port):
    monkeypatch.setenv("APP_PORT", port)
    assert load_settings().port == int(port)


@pytest.mark.parametrize("port", ["", "abc", "1.5", "0", "-1", "65536"])
def test_invalid_port(monkeypatch, port):
    monkeypatch.setenv("APP_PORT", port)
    with pytest.raises(ValueError, match="APP_PORT"):
        load_settings()


def test_invalid_port_exits():
    result = subprocess.run(
        [sys.executable, "-m", "app"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "APP_PORT": "invalid"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "APP_PORT" in result.stderr


def test_llm_defaults(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_MAX_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()
    assert settings.llm_base_url == "http://llm:8080"
    assert settings.llm_model_name == "Qwen3-4B-Instruct-2507"
    assert settings.llm_max_tokens == 768


def test_llm_overrides(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8081/")
    monkeypatch.setenv("LLM_MODEL_NAME", "custom-alias")
    monkeypatch.setenv("LLM_MAX_TOKENS", "128")
    settings = load_settings()
    assert settings.llm_base_url == "http://localhost:8081"
    assert settings.llm_model_name == "custom-alias"
    assert settings.llm_max_tokens == 128


@pytest.mark.parametrize("value", ["", "no", "0", "-1", "1.5"])
def test_invalid_max_tokens(monkeypatch, value):
    monkeypatch.setenv("LLM_MAX_TOKENS", value)
    with pytest.raises(ValueError, match="LLM_MAX_TOKENS"):
        load_settings()
