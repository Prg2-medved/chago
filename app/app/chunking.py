"""Lossless snapshot contract for offline Markdown chunking."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from time import monotonic
from typing import Literal
from urllib.parse import quote, urlsplit

from app.ingestion import Document
from app.chunk_tokenizer import LocalE5, passage


class ChunkingError(ValueError):
    """Controlled diagnostics that contain no source text."""


@dataclass(frozen=True)
class ChunkSettings:
    target: int = 350
    maximum: int = 450
    overlap: int = 50
    input_limit: int = 512

    def __post_init__(self) -> None:
        values = (self.target, self.maximum, self.overlap, self.input_limit)
        if (any(type(value) is not int for value in values)
                or not 0 <= self.overlap < self.target <= self.maximum <= 450
                or not 1 <= self.input_limit <= 512):
            raise ChunkingError("settings")


@dataclass(frozen=True)
class SourceSegment:
    start: int
    end: int
    role: str
    kind: Literal["source"] = "source"

    def text(self, document: Document) -> str:
        if not 0 <= self.start < self.end <= len(document.markdown):
            raise ChunkingError("source_range")
        return document.markdown[self.start:self.end]


@dataclass(frozen=True)
class GeneratedSegment:
    text: str
    reason: Literal["table_header", "fence", "separator"]
    kind: Literal["generated"] = "generated"


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    document: Document
    heading_path: tuple[str, ...]
    ordinal: int
    segments: tuple[SourceSegment | GeneratedSegment, ...]
    search_text: str
    body_tokens: int
    input_tokens: int
    structure: dict[str, object]


@dataclass(frozen=True)
class Snapshot:
    source: str
    documents: tuple[Document, ...]


def parse_snapshot(payload: object) -> Snapshot:
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int:
        raise ChunkingError("snapshot")
    if payload["schema_version"] != 1:
        raise ChunkingError("version")
    source = payload.get("source")
    if not isinstance(source, str):
        raise ChunkingError("source")
    try:
        parts = urlsplit(source)
        valid = (parts.scheme in ("http", "https") and bool(parts.hostname)
                 and parts.username is None and parts.password is None
                 and not parts.path and not parts.query and not parts.fragment
                 and parts.port != 0 and not any(char.isspace() for char in source))
    except ValueError:
        valid = False
    if not valid:
        raise ChunkingError("source")
    rows = payload.get("documents")
    if not isinstance(rows, list):
        raise ChunkingError("documents")
    documents: list[Document] = []
    seen: set[int] = set()
    identities: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ChunkingError("document")
        page_id = row.get("page_id")
        if type(page_id) is not int or page_id < 1 or page_id in seen:
            raise ChunkingError("page_id")

        def text(name: str, empty: bool = False) -> str:
            value = row.get(name)
            if not isinstance(value, str) or (not empty and not value.strip()):
                raise ChunkingError("document_field")
            return value

        locale, path, title, url, timestamp, markdown, digest = (
            text(name, empty=name == "markdown") for name in
            ("locale", "path", "title", "source_url", "updated_at", "markdown", "content_sha256")
        )
        if (locale, path) in identities:
            raise ChunkingError("duplicate_identity")
        if url != f"{source}/{quote(locale, safe='')}/{quote(path, safe='/')}":
            raise ChunkingError("source_url")
        try:
            if (not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", timestamp
            ) or datetime.fromisoformat(timestamp).utcoffset() is None):
                raise ValueError
            actual = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        except (ValueError, UnicodeError):
            raise ChunkingError("document_encoding_or_timestamp") from None
        if digest != actual:
            raise ChunkingError("content_hash")
        documents.append(Document(page_id, locale, path, title, url, timestamp, markdown, digest))
        seen.add(page_id)
        identities.add((locale, path))
    return Snapshot(source, tuple(sorted(documents, key=lambda document: document.page_id)))


def load_snapshot(path: Path) -> Snapshot:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        raise ChunkingError("snapshot_read") from None
    return parse_snapshot(payload)


ALGORITHM_VERSION = "markdown-chunking-1"


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    headings: tuple[str, ...]
    kind: Literal["text", "heading", "code", "table"]
    prefix: str = ""
    suffix: str = ""
    rows: tuple[tuple[int, int], ...] = ()


def pipe_cells(line: str) -> list[str]:
    """Split pipes outside escaped sequences and matching inline-code runs."""
    cells: list[str] = []
    start = 0
    index = 0
    code_run = 0
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char == "`":
            end = index
            while end < len(line) and line[end] == "`":
                end += 1
            length = end - index
            if not code_run:
                code_run = length
            elif code_run == length:
                code_run = 0
            index = end
            continue
        if char == "|" and not code_run:
            cells.append(line[start:index])
            start = index + 1
        index += 1
    cells.append(line[start:].rstrip("\r\n"))
    if cells and not cells[0].strip():
        cells.pop(0)
    if cells and not cells[-1].strip():
        cells.pop()
    return cells


def scan(markdown: str) -> list[Block]:
    lines = markdown.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        headings = tuple(title for _, title in stack)
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
        if fence and (fence[1][0] != "`" or "`" not in fence[2]):
            end = index + 1
            closing = ""
            while end < len(lines):
                candidate = re.fullmatch(
                    r" {0,3}" + re.escape(fence[1][0]) + "{" + str(len(fence[1])) + r",}[ \t]*(?:\r?\n)?",
                    lines[end],
                )
                end += 1
                if candidate:
                    closing = lines[end - 1]
                    break
            blocks.append(Block(offsets[index], offsets[end], headings, "code",
                                line, closing or fence[1] + "\n"))
            index = end
            continue
        atx = re.fullmatch(r" {0,3}(#{1,6})(?:[ \t]+([^\r\n]*)|[ \t]*)(?:\r?\n)?", line)
        setext = (index + 1 < len(lines) and line.strip()
                  and not line.startswith(("    ", "\t"))
                  and re.fullmatch(r" {0,3}(=+|-+)[ \t]*(?:\r?\n)?", lines[index + 1]))
        if atx or setext:
            if atx:
                level = len(atx[1])
                title = re.sub(r"[ \t]+#+[ \t]*$", "", atx[2] or "").strip()
                end = index + 1
            else:
                level = 1 if lines[index + 1].lstrip().startswith("=") else 2
                title = line.strip()
                end = index + 2
            stack = [(depth, value) for depth, value in stack if depth < level]
            stack.append((level, title))
            blocks.append(Block(offsets[index], offsets[end], tuple(value for _, value in stack), "heading"))
            index = end
            continue
        if index + 1 < len(lines) and "|" in line:
            header = pipe_cells(line)
            separator = pipe_cells(lines[index + 1])
            if header and len(header) == len(separator) and all(
                re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in separator
            ):
                end = index + 2
                rows = [(offsets[index], offsets[end])]
                while end < len(lines) and "|" in lines[end] and len(pipe_cells(lines[end])) == len(header):
                    rows.append((offsets[end], offsets[end + 1]))
                    end += 1
                blocks.append(Block(offsets[index], offsets[end], headings, "table",
                                    lines[index] + lines[index + 1], rows=tuple(rows)))
                index = end
                continue
        # Adjacent fallback lines share a block, preserving every source character.
        if blocks and blocks[-1].kind == "text" and blocks[-1].headings == headings:
            previous = blocks.pop()
            blocks.append(Block(previous.start, offsets[index + 1], headings, "text"))
        else:
            blocks.append(Block(offsets[index], offsets[index + 1], headings, "text"))
        index += 1
    return blocks


def chunk_document(source: str, document: Document, tokenizer: LocalE5,
                   settings: ChunkSettings) -> list[Chunk]:
    chunks: list[Chunk] = []
    pending: list[SourceSegment | GeneratedSegment] = []
    pending_headings: tuple[str, ...] = ()

    def render(segments: Sequence[SourceSegment | GeneratedSegment]) -> str:
        return "".join(segment.text(document) if isinstance(segment, SourceSegment)
                       else segment.text for segment in segments)

    def fits(segments: Sequence[SourceSegment | GeneratedSegment], headings: tuple[str, ...],
             limit: int | None = None) -> bool:
        text = render(segments)
        return (tokenizer.count(text) <= (settings.maximum if limit is None else limit)
                and tokenizer.count(passage(document.title, headings, text), True) <= settings.input_limit)

    def emit(segments: Sequence[SourceSegment | GeneratedSegment], headings: tuple[str, ...],
             structure: dict[str, object] | None = None) -> None:
        if not segments:
            return
        if not fits(segments, headings):
            raise ChunkingError(f"budget page_id={document.page_id}")
        text = render(segments)
        ordinal = len(chunks)
        description = {"source": source, "document": asdict(document), "headings": headings,
                       "ordinal": ordinal, "segments": [asdict(segment) for segment in segments],
                       "structure": structure or {}, "settings": asdict(settings),
                       "tokenizer": tokenizer.identity, "algorithm_version": ALGORITHM_VERSION}
        chunk_id = hashlib.sha256(json.dumps(description, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        chunks.append(Chunk(chunk_id, source, document, headings, ordinal, tuple(segments), text,
                            tokenizer.count(text), tokenizer.count(passage(document.title, headings, text), True),
                            structure or {}))

    def flush() -> None:
        nonlocal pending
        emit(pending, pending_headings)
        pending = []

    def split_range(start: int, end: int, headings: tuple[str, ...], role: str,
                    prefix: str = "", suffix: str = "", reason: Literal["table_header", "fence"] = "fence",
                    closed_source: bool = True
                    ) -> list[list[SourceSegment | GeneratedSegment]]:
        parts: list[list[SourceSegment | GeneratedSegment]] = []
        position = start
        while position < end:
            def candidate(stop: int) -> list[SourceSegment | GeneratedSegment]:
                segments: list[SourceSegment | GeneratedSegment] = []
                if prefix and (reason == "table_header" or position > start):
                    segments.append(GeneratedSegment(prefix, reason))
                segments.append(SourceSegment(position, stop, role))
                if suffix and (stop < end or not closed_source):
                    segments.append(GeneratedSegment(suffix, "fence"))
                return segments

            # Prefer complete source lines. A bounded Unicode fallback verifies every
            # accepted candidate; token counts need not be monotone for correctness.
            stop = position
            for line in document.markdown[position:end].splitlines(keepends=True):
                next_stop = stop + len(line)
                if not fits(candidate(next_stop), headings):
                    break
                stop = next_stop
                if tokenizer.count(render(candidate(stop))) >= settings.target:
                    break
            if stop == position:
                size = min(end - position, 2048)
                while size > 0 and not fits(candidate(position + size), headings):
                    size //= 2
                if size == 0:
                    raise ChunkingError(f"budget page_id={document.page_id}")
                stop = position + size
            parts.append(candidate(stop))
            position = stop
        return parts

    for block in scan(document.markdown):
        if pending and pending_headings != block.headings:
            flush()
        pending_headings = block.headings
        segment = SourceSegment(block.start, block.end, block.kind)
        if block.kind in ("code", "table"):
            block_id = hashlib.sha256(f"{source}:{document.page_id}:{block.start}:{block.end}".encode()).hexdigest()
            if fits([segment], block.headings):
                flush()
                structure: dict[str, object]
                if block.kind == "code":
                    structure = {"block_id": block_id, "part_index": 0,
                                 "continued_before": False, "continued_after": False,
                                 "requires_complete_block": False, "split_line": False,
                                 "language_fence": block.prefix.rstrip("\r\n")}
                else:
                    structure = {"table_id": block_id, "part_index": 0,
                                 "rows": [{"row_index": index, "start": start, "end": end}
                                          for index, (start, end) in enumerate(block.rows)]}
                emit([segment], block.headings, structure)
                continue
            flush()
            if block.kind == "code":
                parts = split_range(block.start, block.end, block.headings, "code",
                                    block.prefix, "\n" + block.suffix,
                                    closed_source=document.markdown[block.start:block.end].endswith(block.suffix))
                for part_index, part in enumerate(parts):
                    src = next(item for item in part if isinstance(item, SourceSegment))
                    emit(part, block.headings, {
                        "block_id": block_id, "part_index": part_index,
                        "continued_before": part_index > 0, "continued_after": part_index + 1 < len(parts),
                        "requires_complete_block": True,
                        "split_line": ((src.start > block.start and document.markdown[src.start - 1] != "\n")
                                       or (src.end < block.end and document.markdown[src.end - 1] != "\n")),
                        "language_fence": block.prefix.rstrip("\r\n"),
                    })
            else:
                header_start, header_end = block.rows[0]
                header_segment = SourceSegment(header_start, header_end, "table_header")
                if not fits([header_segment], block.headings):
                    raise ChunkingError(f"table_header_budget page_id={document.page_id}")
                emit([header_segment], block.headings, {"table_id": block_id, "row_index": 0, "part_index": 0})
                for row_index, (start, end) in enumerate(block.rows[1:], 1):
                    parts = split_range(start, end, block.headings, "table_row", block.prefix,
                                        reason="table_header")
                    for part_index, part in enumerate(parts):
                        emit(part, block.headings, {"table_id": block_id, "row_index": row_index,
                             "part_index": part_index, "continued_before": part_index > 0,
                             "continued_after": part_index + 1 < len(parts)})
            continue
        if fits([*pending, segment], block.headings, settings.target):
            pending.append(segment)
            continue
        flush()
        if fits([segment], block.headings):
            pending.append(segment)
            continue
        parts = split_range(block.start, block.end, block.headings, block.kind)
        previous: SourceSegment | None = None
        for part in parts:
            current = next(item for item in part if isinstance(item, SourceSegment))
            overlap: SourceSegment | None = None
            if previous is not None and block.kind == "text" and settings.overlap:
                start = previous.end - 1
                while start > previous.start and tokenizer.count(document.markdown[start - 1:previous.end]) <= settings.overlap:
                    start -= 1
                while start < previous.end:
                    candidate_overlap = SourceSegment(start, previous.end, "overlap")
                    if (tokenizer.count(candidate_overlap.text(document)) <= settings.overlap
                            and fits([candidate_overlap, *part], block.headings)):
                        overlap = candidate_overlap
                        break
                    start += 1
            emit([overlap, *part] if overlap else part, block.headings)
            previous = current
    flush()
    return chunks


def build_output(snapshot: Snapshot, tokenizer: LocalE5, settings: ChunkSettings) -> dict[str, object]:
    chunks = [chunk for document in snapshot.documents
              for chunk in chunk_document(snapshot.source, document, tokenizer, settings)]
    records: list[dict[str, object]] = []
    for chunk in chunks:
        metadata = asdict(chunk.document)
        metadata.pop("markdown")
        records.append({**metadata, "chunk_id": chunk.chunk_id, "source": chunk.source,
                        "heading_path": chunk.heading_path, "ordinal": chunk.ordinal,
                        "segments": [asdict(segment) for segment in chunk.segments],
                        "source_ranges": [[segment.start, segment.end] for segment in chunk.segments
                                          if isinstance(segment, SourceSegment)],
                        "search_text": chunk.search_text, "body_tokens": chunk.body_tokens,
                        "input_tokens": chunk.input_tokens, "structure": chunk.structure})
    return {"schema_version": 1, "algorithm_version": ALGORITHM_VERSION,
            "source": snapshot.source, "tokenizer": tokenizer.identity, "settings": asdict(settings),
            "documents": [asdict(document) for document in snapshot.documents], "chunks": records}


def output_bytes(output: dict[str, object]) -> bytes:
    return (json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def protect_paths(input_path: Path, output: Path, tokenizer_path: Path) -> None:
    resolved = output.resolve()
    assets = tokenizer_path.resolve()
    if resolved == input_path.resolve() or resolved == assets or assets in resolved.parents:
        raise ChunkingError("output_path")
    if output.exists():
        if os.path.samefile(output, input_path):
            raise ChunkingError("output_path")
        for asset in assets.rglob("*"):
            if asset.is_file() and os.path.samefile(output, asset):
                raise ChunkingError("output_path")


def write_output(output: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, output)
    except OSError:
        raise ChunkingError("output_write") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline lossless Markdown chunking")
    for name in ("input", "output", "tokenizer-path"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--target", type=int, default=350)
    parser.add_argument("--maximum", type=int, default=450)
    parser.add_argument("--overlap", type=int, default=50)
    parser.add_argument("--input-limit", type=int, default=512)
    args = parser.parse_args(argv)
    timer = monotonic()
    try:
        protect_paths(args.input, args.output, args.tokenizer_path)
        settings = ChunkSettings(args.target, args.maximum, args.overlap, args.input_limit)
        snapshot = load_snapshot(args.input)
        tokenizer = LocalE5(args.tokenizer_path)
        result = build_output(snapshot, tokenizer, settings)
        write_output(args.output, output_bytes(result))
    except (ValueError, OSError) as error:
        category = (str(error) if isinstance(error, ChunkingError) else
                    "tokenizer_assets" if isinstance(error, ValueError) else "filesystem")
        print(f"chunking: {category}", file=sys.stderr)
        return 1
    records = result["chunks"]
    assert isinstance(records, list)
    print(json.dumps({"documents": len(snapshot.documents), "chunks": len(records),
                      "max_body_tokens": max((record["body_tokens"] for record in records), default=0),
                      "max_input_tokens": max((record["input_tokens"] for record in records), default=0),
                      "duration_seconds": round(monotonic() - timer, 3)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
