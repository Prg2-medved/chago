from pathlib import Path

import pytest

from app.chunk_tokenizer import MODEL_ID, REVISION
from app.config import load_embedding_settings, load_settings


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for name in ("MODEL_PATH", "MODEL_ID", "MODEL_REVISION", "BATCH_SIZE", "CPU_THREADS"):
        monkeypatch.delenv(f"EMBEDDING_{name}", raising=False)


def test_defaults():
    settings = load_embedding_settings()
    assert settings.model_path == Path(f"/data/models/{REVISION}")
    assert (settings.model_id, settings.revision) == (MODEL_ID, REVISION)
    assert (settings.batch_size, settings.cpu_threads) == (16, 4)


def test_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBEDDING_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "8")
    monkeypatch.setenv("EMBEDDING_CPU_THREADS", "2")
    settings = load_embedding_settings()
    assert settings.model_path == tmp_path
    assert (settings.batch_size, settings.cpu_threads) == (8, 2)


@pytest.mark.parametrize("name", ["BATCH_SIZE", "CPU_THREADS"])
@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "sensitive-value"])
def test_invalid_positive_safe(monkeypatch, name, value):
    monkeypatch.setenv(f"EMBEDDING_{name}", value)
    with pytest.raises(ValueError, match=f"EMBEDDING_{name}") as error:
        load_embedding_settings()
    assert "sensitive-value" not in str(error.value)


@pytest.mark.parametrize("name,value", [
    ("MODEL_PATH", ""), ("MODEL_PATH", " "),
    ("MODEL_ID", "other-model"), ("MODEL_REVISION", "other-revision"),
])
def test_invalid_path_identity_http_independent(monkeypatch, name, value):
    monkeypatch.setenv(f"EMBEDDING_{name}", value)
    with pytest.raises(ValueError):
        load_embedding_settings()
    assert load_settings().port == 8000


def test_compose_defaults_documented():
    root = Path(__file__).resolve().parents[2]
    example = (root / ".env.example").read_text()
    compose = (root / "compose.yaml").read_text()
    for name, value in {
        "MODEL_PATH": f"/data/models/{REVISION}", "MODEL_ID": MODEL_ID,
        "MODEL_REVISION": REVISION, "BATCH_SIZE": "16", "CPU_THREADS": "4",
    }.items():
        assert f"EMBEDDING_{name}={value}" in example
        assert f"${{EMBEDDING_{name}:-{value}}}" in compose
