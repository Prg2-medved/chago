from dataclasses import asdict
import hashlib
import json

import pytest

from app.chunking import ChunkingError, ChunkSettings, SourceSegment, load_snapshot, parse_snapshot


def snapshot(markdown="Русский 😀\r\nкоманда\r\n"):
    return {"schema_version": 1, "source": "https://wiki.example", "documents": [{
        "page_id": 1, "locale": "ru", "path": "test", "title": "Test",
        "source_url": "https://wiki.example/ru/test", "updated_at": "2026-10-01T12:00:00Z",
        "markdown": markdown, "content_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
    }]}


def test_snapshot_preserves_unicode_crlf_and_metadata(tmp_path):
    payload = snapshot()
    path = tmp_path / "snapshot.json"
    path.write_bytes(json.dumps(payload, ensure_ascii=False).encode())
    result = load_snapshot(path)
    document = result.documents[0]
    assert asdict(document) == payload["documents"][0]
    assert SourceSegment(8, 9, "text").text(document) == "😀"
    assert SourceSegment(9, 11, "text").text(document) == "\r\n"
    with pytest.raises(ChunkingError, match="source_range"):
        SourceSegment(0, len(document.markdown) + 1, "text").text(document)


def test_empty_snapshot_and_document():
    payload = snapshot("")
    assert parse_snapshot(payload).documents[0].markdown == ""
    payload["documents"] = []
    assert parse_snapshot(payload).documents == ()


@pytest.mark.parametrize("field", ["page_id", "locale", "path", "title", "source_url",
                                   "updated_at", "markdown", "content_sha256"])
@pytest.mark.parametrize("value", [None, [], True])
def test_invalid_document_types(field, value):
    payload = snapshot()
    payload["documents"][0][field] = value
    with pytest.raises(ChunkingError):
        parse_snapshot(payload)


@pytest.mark.parametrize("field,value", [
    ("page_id", 0), ("content_sha256", "0" * 64),
    ("source_url", "https://other.example/ru/test"),
    ("updated_at", "2026-02-30T12:00:00Z"), ("updated_at", "2026-10-01"),
])
def test_invalid_document_values(field, value):
    payload = snapshot()
    payload["documents"][0][field] = value
    with pytest.raises(ChunkingError):
        parse_snapshot(payload)


def test_duplicate_ids():
    payload = snapshot()
    payload["documents"] *= 2
    with pytest.raises(ChunkingError, match="page_id"):
        parse_snapshot(payload)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("documents", {}),
    ("source", "https://wiki.example/"), ("source", "https://user:secret@wiki.example"),
    ("source", "file:///wiki"), ("source", "https://wiki.example:invalid"),
])
def test_invalid_snapshot(field, value):
    payload = snapshot()
    payload[field] = value
    with pytest.raises(ChunkingError) as error:
        parse_snapshot(payload)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("settings", [
    {"target": True}, {"maximum": 451}, {"overlap": 350}, {"overlap": -1},
    {"input_limit": 513}, {"target": 0}, {"target": 451},
])
def test_invalid_settings(settings):
    with pytest.raises(ChunkingError, match="settings"):
        ChunkSettings(**settings)
