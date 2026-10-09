import pytest

from app.config import RetrievalSettings, load_retrieval_settings, load_settings


@pytest.fixture(autouse=True)
def clear_settings(monkeypatch):
    for suffix in ("SEMANTIC_CANDIDATES", "LEXICAL_CANDIDATES", "RRF_CONSTANT", "TOP_K"):
        monkeypatch.delenv("RETRIEVAL_" + suffix, raising=False)


def test_defaults_environment_overrides(monkeypatch):
    assert load_retrieval_settings() == RetrievalSettings(10, 10, 60, 6)
    monkeypatch.setenv("RETRIEVAL_SEMANTIC_CANDIDATES", "20")
    monkeypatch.setenv("RETRIEVAL_LEXICAL_CANDIDATES", "30")
    monkeypatch.setenv("RETRIEVAL_RRF_CONSTANT", "40")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "8")
    assert load_retrieval_settings() == RetrievalSettings(20, 30, 40, 8)
    assert load_retrieval_settings(semantic_candidates=2, lexical_candidates=3, rrf_constant=4, top_k=5) == RetrievalSettings(2, 3, 4, 5)


@pytest.mark.parametrize("field", ["semantic_candidates", "lexical_candidates", "rrf_constant", "top_k"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.2, "2"])
def test_invalid_typed_and_overrides(field, value):
    with pytest.raises(ValueError):
        RetrievalSettings(**{field: value})
    with pytest.raises(ValueError):
        load_retrieval_settings(**{field: value})


@pytest.mark.parametrize("value", ["true", "0", "-1", "1.2", "", " ", "sensitive"])
def test_invalid_env_http_independence(monkeypatch, value):
    monkeypatch.setenv("RETRIEVAL_TOP_K", value)
    with pytest.raises(ValueError, match="^configuration: retrieval_settings$"):
        load_retrieval_settings()
    assert load_settings().port == 8000
    assert load_retrieval_settings(top_k=5).top_k == 5
