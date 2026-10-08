from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

import pytest

from app.index_storage import StorageError, StorageReader, parse_output, write_snapshot
from test_chunking import snapshot


def output(markdown="Русский 😀\r\n```py\r\nx=1\r\n```\r\n| a |\r\n|---|\r\n| б |\r\n"):
    data = snapshot(markdown)
    hashes = {"tokenizer.json": "a" * 64}
    data.update(algorithm_version="markdown-chunking-1",
                tokenizer={"model_id": "intfloat/multilingual-e5-small", "revision": "test",
                           "package": "tokenizers", "package_version": "0.22.2",
                           "assets_sha256": hashes,
                           "assets_fingerprint": hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()},
                settings={"target": 350, "maximum": 450, "overlap": 50, "input_limit": 512}, chunks=[])
    if markdown:
        doc = {key: value for key, value in data["documents"][0].items() if key != "markdown"}
        data["chunks"] = [{**doc, "chunk_id": "b" * 64, "source": data["source"],
                           "heading_path": ["Заголовок", "😀"], "ordinal": 0,
                           "segments": [{"kind": "generated", "reason": "fence", "text": "```\n"},
                                        {"kind": "source", "start": 0, "end": len(markdown), "role": "code"},
                                        {"kind": "generated", "reason": "separator", "text": "\n"},
                                        {"kind": "generated", "reason": "table_header", "text": "|a|\n"}],
                           "source_ranges": [[0, len(markdown)]], "search_text": "```\n" + markdown + "\n|a|\n",
                           "body_tokens": 35, "input_tokens": 45,
                           "structure": {"block_id": "c" * 64, "continued_before": True,
                                         "rows": [{"start": 0, "end": 5}, {"start": 6, "end": 9}]}}]
    return data


def test_parser_offline(monkeypatch):
    monkeypatch.delenv("WIKI_TOKEN", raising=False)
    monkeypatch.setitem(sys.modules, "app.chunk_tokenizer", None)
    monkeypatch.setitem(sys.modules, "tokenizers", None)
    parsed = parse_output(output())
    assert parsed.documents[0].markdown == output()["documents"][0]["markdown"]
    assert parsed.chunks[0].segments[1]["kind"] == "source"


@pytest.mark.parametrize("empty_documents", [False, True])
def test_empty(tmp_path, empty_documents):
    data = output("")
    if empty_documents:
        data["documents"] = []
    parsed = parse_output(data)
    path = tmp_path / "empty.db"
    write_snapshot(path, parsed)
    with StorageReader(path) as reader:
        assert reader.snapshot == parsed
        assert reader.chunks == ()


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("source", "https://user:secret@wiki.example"),
    ("source", "https://wiki.example/"), ("algorithm_version", None),
    ("documents", {}), ("chunks", {}), ("tokenizer", {}), ("settings", {}),
])
def test_invalid_top_level(field, value):
    data = output()
    data[field] = value
    with pytest.raises(StorageError) as error:
        parse_output(data)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("field", ["page_id", "locale", "path", "title", "source_url", "updated_at", "markdown", "content_sha256"])
@pytest.mark.parametrize("value", [None, [], True])
def test_document_types(field, value):
    data = output()
    data["documents"][0][field] = value
    with pytest.raises(StorageError):
        parse_output(data)


@pytest.mark.parametrize("field,value", [
    ("page_id", 0), ("content_sha256", "d" * 64), ("source_url", "https://other/ru/test"),
    ("updated_at", "2026-02-30T12:00:00Z"), ("updated_at", "2026-10-01"),
])
def test_document_values(field, value):
    data = output()
    data["documents"][0][field] = value
    with pytest.raises(StorageError):
        parse_output(data)


@pytest.mark.parametrize("field,value", [
    ("page_id", 99), ("page_id", True), ("title", "wrong"), ("source", "https://other"),
    ("chunk_id", "invalid"), ("ordinal", True), ("ordinal", -1), ("ordinal", 1),
    ("heading_path", "heading"), ("heading_path", [1]), ("body_tokens", True),
    ("body_tokens", 451), ("input_tokens", 513), ("input_tokens", -1),
    ("segments", []), ("segments", [{"kind": "unknown"}]),
    ("segments", [{"kind": "source", "start": True, "end": 1, "role": "text"}]),
    ("segments", [{"kind": "source", "start": 0, "end": 10000, "role": "text"}]),
    ("segments", [{"kind": "source", "start": 1, "end": 1, "role": "text"}]),
    ("segments", [{"kind": "source", "start": 0, "end": 1, "role": "unknown"}]),
    ("segments", [{"kind": "generated", "text": "x", "reason": "unknown"}]),
    ("source_ranges", [[True, 1]]), ("source_ranges", [[0, 1]]),
    ("source_ranges", []), ("search_text", "wrong"), ("structure", []),
])
def test_chunk_rejection(field, value):
    data = output()
    data["chunks"][0][field] = value
    with pytest.raises(StorageError):
        parse_output(data)


@pytest.mark.parametrize("kind", ["document_id", "document_identity", "chunk_id", "ordinal"])
def test_duplicates(kind):
    data = output()
    if kind.startswith("document"):
        row = deepcopy(data["documents"][0])
        if kind == "document_identity":
            row["page_id"] = 2
        data["documents"].append(row)
    else:
        row = deepcopy(data["chunks"][0])
        if kind == "ordinal":
            row["chunk_id"] = "c" * 64
        data["chunks"].append(row)
    with pytest.raises(StorageError):
        parse_output(data)


@pytest.mark.parametrize("field,value", [("target", True), ("maximum", 451), ("overlap", 350), ("overlap", -1), ("input_limit", 513)])
def test_settings(field, value):
    data = output()
    data["settings"][field] = value
    with pytest.raises(StorageError):
        parse_output(data)


@pytest.mark.parametrize("field,value", [("revision", None), ("assets_fingerprint", "0" * 64), ("assets_sha256", {}), ("assets_sha256", {"tokenizer.json": True})])
def test_tokenizer_metadata(field, value):
    data = output()
    data["tokenizer"][field] = value
    with pytest.raises(StorageError):
        parse_output(data)


def test_roundtrip_and_replacement(tmp_path):
    data = output()
    parsed = parse_output(data)
    path = tmp_path / "storage.db"
    for _ in range(2):
        write_snapshot(path, parsed)
        with StorageReader(path) as reader:
            assert reader.snapshot == parsed
            assert asdict(reader.documents[0]) == data["documents"][0]
            chunk = reader.get_chunk(parsed.chunks[0].chunk_id)
            assert chunk == parsed.chunks[0]
            assert reader.get_chunk("unknown") is None
            assert chunk.segments == tuple(data["chunks"][0]["segments"])
            assert chunk.structure == data["chunks"][0]["structure"]
            assert chunk.document.markdown[8:9] == "😀"
            assert chunk.document.markdown[9:11] == "\r\n"
    data["documents"] = []
    data["chunks"] = []
    write_snapshot(path, parse_output(data))
    with StorageReader(path) as reader:
        assert not reader.documents and not reader.chunks
    assert not list(tmp_path.glob("*-wal"))
    assert not list(tmp_path.glob("*.tmp*"))


def test_namespaces(tmp_path):
    identities = []
    for source in ("https://wiki.example", "https://other.example"):
        data = output("")
        data["source"] = source
        data["documents"][0]["source_url"] = source + "/ru/test"
        path = tmp_path / "storage.db"
        write_snapshot(path, parse_output(data))
        with StorageReader(path) as reader:
            identities.append((reader.snapshot.source, reader.documents[0].page_id))
    assert identities[0] != identities[1]


def test_stable_ordering(tmp_path):
    data = output()
    second_doc = deepcopy(data["documents"][0])
    second_doc.update(page_id=2, path="second", source_url=data["source"] + "/ru/second")
    second_chunk = deepcopy(data["chunks"][0])
    second_chunk.update(page_id=2, path="second", source_url=second_doc["source_url"], chunk_id="0" * 64)
    continuation = deepcopy(data["chunks"][0])
    continuation.update(ordinal=1, chunk_id="1" * 64)
    data["documents"].insert(0, second_doc)
    data["chunks"] = [second_chunk, continuation, data["chunks"][0]]
    path = tmp_path / "ordered.db"
    write_snapshot(path, parse_output(data))
    with StorageReader(path) as reader:
        assert [doc.page_id for doc in reader.documents] == [1, 2]
        assert [(chunk.document.page_id, chunk.ordinal) for chunk in reader.chunks] == [(1, 0), (1, 1), (2, 0)]


def test_schema_constraints(tmp_path):
    path = tmp_path / "storage.db"
    write_snapshot(path, parse_output(output()))
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in (
            "INSERT INTO documents SELECT * FROM documents",
            "INSERT INTO chunks SELECT * FROM chunks",
            "UPDATE chunks SET page_id=99",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement)


def test_partial_transaction_failure(tmp_path):
    from app.index_storage import _write_database
    path = tmp_path / "storage.db"
    parsed = parse_output(output())
    write_snapshot(path, parsed)
    before = path.read_bytes()

    def fail_after_document_write(temporary, snapshot):
        # A duplicate chunk causes failure after document insertion in the transaction.
        from dataclasses import replace
        _write_database(temporary, replace(snapshot, chunks=snapshot.chunks * 2))

    with patch("app.index_storage._write_database", side_effect=fail_after_document_write):
        with pytest.raises(StorageError, match="^output_write$"):
            write_snapshot(path, parsed)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp*"))


@pytest.mark.parametrize("problem", ["missing", "corrupt", "version", "metadata", "orphan", "schema"])
def test_reader_rejects(tmp_path, problem):
    path = tmp_path / "storage.db"
    if problem == "corrupt":
        path.write_bytes(b"corrupt")
    elif problem != "missing":
        write_snapshot(path, parse_output(output()))
        with sqlite3.connect(path) as connection:
            if problem == "version":
                connection.execute("PRAGMA user_version=2")
            elif problem == "metadata":
                connection.execute("UPDATE snapshot_metadata SET tokenizer='{}'")
            elif problem == "orphan":
                connection.execute("UPDATE chunks SET page_id=99")
            elif problem == "schema":
                connection.execute("DROP TABLE chunks")
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(StorageError):
        StorageReader(path)
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("failure", ["write", "check", "replace"])
def test_atomic_failures(tmp_path, failure):
    path = tmp_path / "storage.db"
    old = parse_output(output())
    write_snapshot(path, old)
    before = path.read_bytes()
    target = {"write": "_write_database", "check": "StorageReader", "replace": "os.replace"}[failure]
    with patch("app.index_storage." + target, side_effect=OSError("secret source text")):
        with pytest.raises(StorageError, match="^output_write$"):
            write_snapshot(path, old)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp*"))


def test_real_chunking_output(tmp_path):
    from app.chunk_tokenizer import LocalE5, REVISION
    from app.chunking import ChunkSettings, build_output, parse_snapshot
    assets = Path(__file__).resolve().parents[2] / "data/tokenizers" / REVISION
    if not assets.is_dir():
        pytest.skip("local E5 assets unavailable")
    markdown = "# Русский 😀\r\n" + "строка текста\r\n" * 150 + "```py\r\n" + "print('б')\r\n" * 150 + "```\r\n|a|b|\r\n|---|---|\r\n" + "|значение|текст|\r\n" * 150
    data = build_output(parse_snapshot(snapshot(markdown)), LocalE5(assets), ChunkSettings())
    parsed = parse_output(data)
    path = tmp_path / "real.db"
    write_snapshot(path, parsed)
    with StorageReader(path) as reader:
        assert reader.snapshot == parsed
        for chunk in reader.chunks:
            pieces = [chunk.document.markdown[segment["start"]:segment["end"]]
                      if segment["kind"] == "source" else segment["text"] for segment in chunk.segments]
            assert "".join(pieces) == chunk.search_text
