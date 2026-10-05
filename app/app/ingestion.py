import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from time import monotonic
from urllib.parse import quote

from app.config import IngestionSettings, load_ingestion_settings
from app.wiki_client import IngestionError, fetch_pages


@dataclass(frozen=True)
class Document:
    page_id: int
    locale: str
    path: str
    title: str
    source_url: str
    updated_at: str
    markdown: str
    content_sha256: str

    @property
    def length(self) -> int:
        return len(self.markdown)


def build_documents(rows: Iterable[Mapping[str, object]], source: str) -> list[Document]:
    documents: list[Document] = []
    seen: set[int] = set()
    for row in rows:
        try:
            def text(name: str) -> str:
                value = row[name]
                if not isinstance(value, str):
                    raise ValueError
                return value

            page_id = row["page_id"]
            if not isinstance(page_id, int) or isinstance(page_id, bool) or page_id < 1 or page_id in seen:
                raise ValueError
            locale, path, title, markdown, updated_at = (
                text(name) for name in ("locale", "path", "title", "markdown", "updated_at")
            )
            if not locale.strip() or not path.strip() or not title.strip():
                raise ValueError
            # Reject permissive fromisoformat forms such as a bare date or space separator.
            if not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
                updated_at,
            ):
                raise ValueError
            timestamp = datetime.fromisoformat(updated_at)
            if timestamp.utcoffset() is None:
                raise ValueError
            normalized = timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            source_url = f"{source}/{quote(locale, safe='')}/{quote(path, safe='/')}"
            documents.append(Document(page_id, locale, path, title, source_url, normalized, markdown, digest))
            seen.add(page_id)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise IngestionError("invalid row") from None
    return sorted(documents, key=lambda document: document.page_id)


def write_snapshot(output: Path, source: str, documents: Sequence[Document]) -> None:
    temporary: Path | None = None
    try:
        payload = json.dumps(
            {"schema_version": 1, "source": source,
             "documents": [asdict(document) for document in sorted(documents, key=lambda item: item.page_id)]},
            ensure_ascii=False, sort_keys=True, indent=2,
        ) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, output)
        os.chmod(output, 0o644)
    except (OSError, ValueError, TypeError):
        raise IngestionError("output") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Cleanup must not expose filesystem diagnostics or hide the safe error.
                pass


def ingest(settings: IngestionSettings, output: Path) -> list[Document]:
    rows = fetch_pages(settings)
    documents = build_documents(rows, settings.source_origin)
    write_snapshot(output, settings.source_origin, documents)
    return documents


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save a complete Wiki.js Markdown snapshot")
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    started = datetime.now(timezone.utc)
    timer = monotonic()
    try:
        settings = load_ingestion_settings()
        documents = ingest(settings, arguments.output)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except IngestionError as error:
        print(f"ingestion: {error}", file=sys.stderr)
        return 1
    for document in documents:
        # JSON quoting keeps multiline titles/paths on a single report line.
        print(json.dumps({"title": document.title, "path": document.path, "length": document.length}, ensure_ascii=False))
    print(f"started_at={started.isoformat()} duration_seconds={monotonic() - timer:.3f}")
    print(f"received={len(documents)} saved={len(documents)} output={arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
