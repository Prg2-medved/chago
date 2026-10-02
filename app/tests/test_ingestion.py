from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock

import psycopg
import pytest

from app.config import IngestionSettings
from app.ingestion import build_documents, ingest, main, write_snapshot
from app.wiki_client import IngestionError


SOURCE = "https://wiki.example"


@pytest.fixture
def rows():
    return json.loads((Path(__file__).parent / "fixtures/wiki-pages.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings():
    return IngestionSettings("localhost", "wiki", "reader", "fixture-only", SOURCE)


def test_lossless_documents(rows):
    documents = build_documents(rows, SOURCE)
    assert [document.page_id for document in documents] == [1, 2]
    assert documents[0].length == 0
    assert documents[0].content_sha256 == hashlib.sha256(b"").hexdigest()
    assert documents[1].length == len(rows[0]["markdown"])
    assert documents[1].content_sha256 == hashlib.sha256(rows[0]["markdown"].encode("utf-8")).hexdigest()
    assert documents[0].updated_at == documents[1].updated_at == "2026-10-01T12:34:56.789000Z"
    assert documents[1].source_url == SOURCE + "/ru/%D1%81%D0%BF%D1%80%D0%B0%D0%B2%D0%BA%D0%B0/%D0%9D%D0%B0%D1%87%D0%B0%D0%BB%D0%BE%20%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%8B"
    with pytest.raises(FrozenInstanceError):
        documents[0].title = "changed"
    assert json.loads(json.dumps(documents[1].markdown, ensure_ascii=False)) == rows[0]["markdown"]


def test_snapshot_contract(rows, tmp_path):
    documents = build_documents(rows, SOURCE)
    output = tmp_path / "snapshot.json"
    write_snapshot(output, SOURCE, documents)
    payload = output.read_bytes()
    assert payload.endswith(b"\n") and not payload.endswith(b"\n\n")
    assert "Пример".encode() in payload
    snapshot = json.loads(payload)
    assert snapshot["schema_version"] == 1
    assert snapshot["source"] == SOURCE
    assert snapshot["documents"][1]["markdown"] == rows[0]["markdown"]
    assert set(snapshot) == {"schema_version", "source", "documents"}


@pytest.mark.parametrize("field", ["page_id", "locale", "path", "title", "markdown", "updated_at"])
@pytest.mark.parametrize("operation", ["missing", "null", "wrong_type"])
def test_invalid_fields(rows, field, operation):
    row = rows[0]
    if operation == "missing":
        del row[field]
    else:
        row[field] = None if operation == "null" else ("1" if field == "page_id" else 42)
    with pytest.raises(IngestionError, match="invalid row"):
        build_documents(rows, SOURCE)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5])
def test_invalid_id(rows, value):
    rows[0]["page_id"] = value
    with pytest.raises(IngestionError, match="invalid row"):
        build_documents(rows, SOURCE)


@pytest.mark.parametrize("field", ["locale", "path", "title"])
@pytest.mark.parametrize("value", ["", " \t"])
def test_empty_metadata(rows, field, value):
    rows[0][field] = value
    with pytest.raises(IngestionError):
        build_documents(rows, SOURCE)


@pytest.mark.parametrize("value", [
    "", "secret-date", "2026-10-01", "2026-10-01T12:34:56",
    "2026-02-30T12:34:56Z", "2026-10-01T12:34:56+25:00",
    "2026-10-01T12:34:56+03:99",
])
def test_invalid_date(rows, value):
    rows[0]["updated_at"] = value
    with pytest.raises(IngestionError, match="invalid row") as error:
        build_documents(rows, SOURCE)
    assert error.value.__suppress_context__


def test_duplicate_and_rename(rows):
    with pytest.raises(IngestionError):
        build_documents([rows[0], rows[0]], SOURCE)
    original = build_documents([rows[0]], SOURCE)[0]
    renamed = build_documents([{**rows[0], "path": "новое/имя", "title": "Новое имя"}], SOURCE)[0]
    assert renamed.page_id == original.page_id
    assert renamed.source_url != original.source_url
    assert renamed.markdown == original.markdown
    assert len(build_documents(rows, SOURCE)) == 2  # same path, distinct locale/ID


def test_url_encodes_special_characters(rows):
    rows[0].update(locale="ru", path="a/#?% space")
    assert build_documents([rows[0]], SOURCE)[0].source_url == SOURCE + "/ru/a/%23%3F%25%20space"


def test_determinism_deletion_and_empty(rows, settings, tmp_path, monkeypatch):
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr("app.ingestion.fetch_pages", lambda _: rows)
    ingest(settings, output)
    first = output.read_bytes()
    rows.reverse()
    ingest(settings, output)
    assert output.read_bytes() == first
    rows.pop()
    ingest(settings, output)
    assert len(json.loads(output.read_bytes())["documents"]) == 1
    rows.clear()
    assert ingest(settings, output) == []
    assert json.loads(output.read_bytes())["documents"] == []
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("existing", [True, False])
@pytest.mark.parametrize("failure", ["fetch", "validation", "write", "replace"])
def test_failure_preserves_target(rows, settings, tmp_path, monkeypatch, existing, failure):
    output = tmp_path / "snapshot.json"
    if existing:
        output.write_bytes(b"old snapshot")
    monkeypatch.setattr("app.ingestion.fetch_pages", lambda _: rows)

    def fail(*args, **kwargs):
        raise OSError("private filesystem detail")

    if failure == "fetch":
        def fetch(_):
            raise IngestionError("query")
        monkeypatch.setattr("app.ingestion.fetch_pages", fetch)
    elif failure == "validation":
        rows[0]["markdown"] = None
    elif failure == "write":
        original = tempfile.NamedTemporaryFile
        def broken_file(*args, **kwargs):
            handle = original(*args, **kwargs)
            handle.write = fail
            return handle
        monkeypatch.setattr("app.ingestion.tempfile.NamedTemporaryFile", broken_file)
    else:
        monkeypatch.setattr("app.ingestion.os.replace", fail)
    with pytest.raises(IngestionError):
        ingest(settings, output)
    if existing:
        assert output.read_bytes() == b"old snapshot"
    else:
        assert not output.exists()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("stage", ["fetch", "commit"])
def test_database_failure_does_not_publish(rows, settings, tmp_path, monkeypatch, stage):
    connect = MagicMock()
    connection = connect.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    if stage == "fetch":
        cursor.fetchall.side_effect = psycopg.OperationalError("private rows")
    else:
        connect.return_value.__exit__.side_effect = psycopg.OperationalError("private transaction")
    monkeypatch.setattr("app.wiki_client.psycopg.connect", connect)
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"previous")
    with pytest.raises(IngestionError):
        ingest(settings, output)
    assert output.read_bytes() == b"previous"


def test_cli_success(rows, settings, tmp_path, monkeypatch, capsys):
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr("app.ingestion.load_ingestion_settings", lambda: settings)
    monkeypatch.setattr("app.ingestion.fetch_pages", lambda _: rows)
    assert main(["--output", str(output)]) == 0
    report = capsys.readouterr()
    assert not report.err
    assert "received=2 saved=2" in report.out
    assert "started_at=" in report.out and "duration_seconds=" in report.out
    assert str(output) in report.out
    assert '"length": 0' in report.out
    assert "excluded" not in report.out
    assert "fixture-only" not in report.out


def test_cli_empty(settings, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("app.ingestion.load_ingestion_settings", lambda: settings)
    monkeypatch.setattr("app.ingestion.fetch_pages", lambda _: [])
    assert main(["--output", str(tmp_path / "empty.json")]) == 0
    assert "received=0 saved=0" in capsys.readouterr().out


@pytest.mark.parametrize("category", ["connection", "permission", "query timeout", "query", "invalid row", "output"])
def test_cli_safe_error(settings, tmp_path, monkeypatch, capsys, category):
    monkeypatch.setattr("app.ingestion.load_ingestion_settings", lambda: settings)
    def fail(*args):
        raise IngestionError(category)
    monkeypatch.setattr("app.ingestion.ingest", fail)
    assert main(["--output", str(tmp_path / "snapshot.json")]) == 1
    report = capsys.readouterr()
    assert report.out == ""
    assert report.err == f"ingestion: {category}\n"


def test_cli_configuration_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WIKI_DB_HOST", raising=False)
    assert main(["--output", str(tmp_path / "snapshot.json")]) == 1
    report = capsys.readouterr()
    assert not report.out
    assert "WIKI_DB_HOST" in report.err
    assert not (tmp_path / "snapshot.json").exists()


def test_cli_required_output():
    result = subprocess.run(
        [sys.executable, "-m", "app.ingestion"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "--output" in result.stderr
