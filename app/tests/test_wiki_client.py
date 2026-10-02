from unittest.mock import MagicMock

import psycopg
import pytest

from app.config import IngestionSettings
from app.wiki_client import IngestionError, fetch_pages


@pytest.fixture
def settings():
    return IngestionSettings("localhost", "wiki", "reader", "fixture-only", "https://wiki.example")


@pytest.fixture
def database(monkeypatch):
    connect = MagicMock()
    connection = connect.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [{"page_id": 1}, {"page_id": 2}]
    monkeypatch.setattr("app.wiki_client.psycopg.connect", connect)
    return connect, connection, cursor


def test_complete_read_only(settings, database):
    connect, connection, cursor = database
    assert fetch_pages(settings) == [{"page_id": 1}, {"page_id": 2}]
    kwargs = connect.call_args.kwargs
    assert not connect.call_args.args
    assert kwargs["connect_timeout"] == 30
    assert kwargs["options"] == "-c statement_timeout=30000"
    assert kwargs["password"] == "fixture-only"
    assert connection.read_only is True
    assert cursor.execute.call_args.args[0].as_string() == (
        'SELECT page_id, locale, path, title, markdown, updated_at FROM "rag"."rag_wikijs_pages_v1"'
    )
    assert cursor.execute.call_count == 1
    cursor.fetchall.assert_called_once_with()
    connect.return_value.__exit__.assert_called_once_with(None, None, None)
    connection.cursor.return_value.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("stage", ["connect", "execute", "fetch", "commit"])
@pytest.mark.parametrize("exception,category", [
    (psycopg.OperationalError, None),
    (psycopg.errors.InsufficientPrivilege, "permission"),
    (psycopg.errors.QueryCanceled, "query timeout"),
    (psycopg.ProgrammingError, None),
])
def test_failures(settings, database, stage, exception, category):
    connect, connection, cursor = database
    target = {
        "connect": connect, "execute": cursor.execute,
        "fetch": cursor.fetchall, "commit": connect.return_value.__exit__,
    }[stage]
    target.side_effect = exception("fixture-only driver detail")
    with pytest.raises(IngestionError) as error:
        fetch_pages(settings)
    assert str(error.value) == (category or ("connection" if stage == "connect" else "query"))
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
    if stage != "connect":
        connect.return_value.__exit__.assert_called_once()


def test_interrupted_fetch_has_no_partial_result(settings, database):
    connect, connection, cursor = database

    def interrupted():
        partial_rows = [{"page_id": 1}, {"page_id": 2}]
        assert partial_rows
        raise psycopg.OperationalError("private driver message")

    cursor.fetchall.side_effect = interrupted
    with pytest.raises(IngestionError, match="query"):
        fetch_pages(settings)
