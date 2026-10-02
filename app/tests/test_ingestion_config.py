import pytest

from app.config import load_ingestion_settings, load_settings


@pytest.fixture
def environment(monkeypatch):
    for name in ("WIKI_DB_PORT", "WIKI_DB_VIEW", "WIKI_DB_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "WIKI_DB_HOST": "localhost", "WIKI_DB_NAME": "wiki",
        "WIKI_DB_USER": "reader", "WIKI_DB_PASSWORD": "fixture-only",
        "WIKI_SOURCE_ORIGIN": "https://wiki.example/",
    }.items():
        monkeypatch.setenv(name, value)


def test_defaults_and_secret(environment):
    settings = load_ingestion_settings()
    assert settings.port == 5432
    assert settings.view == "rag.rag_wikijs_pages_v1"
    assert settings.timeout_seconds == 30
    assert settings.source_origin == "https://wiki.example"
    assert "fixture-only" not in repr(settings)


@pytest.mark.parametrize("name", [
    "WIKI_DB_HOST", "WIKI_DB_NAME", "WIKI_DB_USER", "WIKI_DB_PASSWORD", "WIKI_SOURCE_ORIGIN",
])
@pytest.mark.parametrize("value", [None, "", " ", "\x00"])
def test_required(environment, monkeypatch, name, value):
    if value is None:
        monkeypatch.delenv(name)
    elif value == "\x00":
        # Real process environments cannot contain NUL.
        monkeypatch.setattr("app.config.os.environ", {name: value})
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        load_ingestion_settings()


@pytest.mark.parametrize("name,value", [
    ("WIKI_DB_PORT", "0"), ("WIKI_DB_PORT", "65536"),
    ("WIKI_DB_PORT", "sensitive-value"), ("WIKI_DB_PORT", ""),
    ("WIKI_DB_TIMEOUT_SECONDS", "0"), ("WIKI_DB_TIMEOUT_SECONDS", "2147484"),
    ("WIKI_DB_TIMEOUT_SECONDS", "1.5"),
    ("WIKI_DB_VIEW", "rag.pages; DROP TABLE pages"), ("WIKI_DB_VIEW", "pages"),
    ("WIKI_DB_VIEW", "Rag.pages"), ("WIKI_DB_VIEW", "rag." + "x" * 64),
    ("WIKI_SOURCE_ORIGIN", "https://user:sensitive-value@wiki.example"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki.example/path"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki.example?secret"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki.example#secret"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki.example?"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki.example:"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki.example:65536"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki.example:bad"),
    ("WIKI_SOURCE_ORIGIN", "https://wiki. example"),
    ("WIKI_SOURCE_ORIGIN", "ftp://wiki.example"),
])
def test_invalid_safe(environment, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name) as error:
        load_ingestion_settings()
    if value:
        assert value not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize("name,value,attribute", [
    ("WIKI_DB_PORT", "1", "port"), ("WIKI_DB_PORT", "65535", "port"),
    ("WIKI_DB_TIMEOUT_SECONDS", "1", "timeout_seconds"),
    ("WIKI_DB_TIMEOUT_SECONDS", "2147483", "timeout_seconds"),
])
def test_boundaries(environment, monkeypatch, name, value, attribute):
    monkeypatch.setenv(name, value)
    assert getattr(load_ingestion_settings(), attribute) == int(value)


def test_http_independent(monkeypatch):
    for name in ("WIKI_DB_HOST", "WIKI_DB_PASSWORD", "WIKI_SOURCE_ORIGIN"):
        monkeypatch.delenv(name, raising=False)
    assert load_settings().port == 8000
