from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import IngestionSettings


class IngestionError(Exception):
    """Safe diagnostic: never include source rows or driver messages."""


def fetch_pages(settings: IngestionSettings) -> list[dict[str, Any]]:
    phase = "connection"
    try:
        with psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.name,
            user=settings.user,
            password=settings.password,
            connect_timeout=settings.timeout_seconds,
            options=f"-c statement_timeout={settings.timeout_seconds * 1000}",
            row_factory=dict_row,
        ) as connection:
            phase = "query"
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL(
                    "SELECT page_id, locale, path, title, markdown, updated_at FROM {}"
                ).format(sql.Identifier(*settings.view.split("."))))
                rows = cursor.fetchall()
        # Both fetch and transaction completion must succeed before returning.
        return rows
    except psycopg.errors.InsufficientPrivilege:
        raise IngestionError("permission") from None
    except psycopg.errors.QueryCanceled:
        raise IngestionError("query timeout") from None
    except psycopg.Error:
        raise IngestionError(phase) from None
