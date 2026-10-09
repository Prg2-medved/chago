"""Safe unicode61 keyword queries and exact source-backed literal priority v1."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
import ipaddress
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

from app.index_storage import StorageError, StoredChunk
from app.lexical_storage import LexicalReader, LexicalStorageError, _ArgumentParser


class LexicalRetrievalError(ValueError):
    """Safe query error category."""


@dataclass(frozen=True)
class Literal:
    value: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class LiteralMatch:
    literal: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class LexicalResult:
    rank: int
    bm25_score: float | None
    chunk: StoredChunk
    literal_matches: tuple[LiteralMatch, ...]

    def to_dict(self) -> dict[str, Any]:
        chunk = asdict(self.chunk)
        document = chunk.pop("document")
        document.pop("markdown")
        return {"rank": self.rank, "bm25_score": self.bm25_score,
                "literal_matches": [asdict(match) for match in self.literal_matches], **document, **chunk}


_PATH = re.compile(r"(?<![\w:/\\])(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}/|/|[\w.-]+/)[^\s`\"'<>|,;!?()\[\]{}]+")
_IP = re.compile(r"(?<![\w.:])(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9A-Fa-f]*:[0-9A-Fa-f:.%]+)(?![\w:])")
_NAME = re.compile(r"(?<![\w-])[^\W_]+(?:-[^\W_]+)+(?![\w-])", re.UNICODE)
_QUOTED = re.compile(r"(?<!`)`([^`]+)`(?!`)")


def _unquoted(text: str) -> list[Literal]:
    candidates = []
    for pattern, kind in ((_PATH, "path"), (_IP, "ip"), (_NAME, "identifier")):
        for match in pattern.finditer(text):
            value = match.group().rstrip(".:" if kind == "path" else ".")
            if kind == "ip":
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    continue
            if value:
                candidates.append(Literal(value, kind, match.start(), match.start() + len(value)))
    chosen: list[Literal] = []
    for literal in sorted(candidates, key=lambda item: (-(item.end - item.start), item.start, item.kind)):
        if not any(literal.start < other.end and other.start < literal.end for other in chosen):
            chosen.append(literal)
    return sorted(chosen, key=lambda item: item.start)


def extract_literals(question: str) -> tuple[Literal, ...]:
    quoted = []
    masked = list(question)
    for match in _QUOTED.finditer(question):
        value = match.group(1)
        if not value.strip():
            continue
        technical = _unquoted(value)
        kind = technical[0].kind if len(technical) == 1 and technical[0].value == value else "quoted"
        quoted.append(Literal(value, kind, match.start(1), match.end(1)))
        masked[match.start():match.end()] = " " * (match.end() - match.start())
    return tuple(sorted([*quoted, *_unquoted("".join(masked))], key=lambda item: item.start))


def _continues(text: str, position: int, kind: str, direction: int) -> bool:
    if not 0 <= position < len(text):
        return False
    char = text[position]
    if char.isalnum() or char == "_":
        return True
    if char == ".":
        # Sentence punctuation is separate, while .bak and extra IP components continue.
        adjacent = position + direction
        return 0 <= adjacent < len(text) and (text[adjacent].isalnum() or text[adjacent] in "_.")
    return char in {"ip": ":%", "path": "/\\-~:+%@", "identifier": "-"}.get(kind, "")


def literal_matches(chunk: StoredChunk, literals: tuple[Literal, ...]) -> tuple[LiteralMatch, ...]:
    intervals: list[tuple[int, int]] = []
    for start, end in sorted(chunk.source_ranges):
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
        else:
            intervals.append((start, end))
    markdown = chunk.document.markdown
    matches = set()
    for literal in literals:
        for start, end in intervals:
            position = markdown.find(literal.value, start, end)
            while position >= 0:
                finish = position + len(literal.value)
                if literal.kind == "quoted" or not (
                    _continues(markdown, position - 1, literal.kind, -1)
                    or _continues(markdown, finish, literal.kind, 1)
                ):
                    matches.add(LiteralMatch(literal.value, literal.kind, position, finish))
                position = markdown.find(literal.value, position + 1, end)
    return tuple(sorted(matches, key=lambda item: (item.start, item.end, item.literal, item.kind)))


def validate_query(question: str, k: int) -> None:
    if type(k) is not int or k < 1:
        raise LexicalRetrievalError("lexical_k")
    if not isinstance(question, str) or not question.strip() or "\x00" in question:
        raise LexicalRetrievalError("lexical_question")
    try:
        question.encode("utf-8")
    except UnicodeError:
        raise LexicalRetrievalError("lexical_question") from None


class LexicalIndex:
    def __init__(self, path: Path) -> None:
        self._reader = LexicalReader(path)
        try:
            self._initialize(self._reader)
        except sqlite3.Error:
            self.close()
            raise LexicalRetrievalError("lexical_query") from None
        except BaseException:
            self.close()
            raise

    @classmethod
    def _from_reader(cls, reader: LexicalReader) -> "LexicalIndex":
        index = cls.__new__(cls)
        index._reader = reader
        try:
            index._initialize(reader)
        except sqlite3.Error:
            index.close()
            raise LexicalRetrievalError("lexical_query") from None
        except BaseException:
            index.close()
            raise
        return index

    def _initialize(self, reader: LexicalReader) -> None:
        self.snapshot = reader.snapshot
        self.chunks = tuple(sorted(reader.chunks, key=lambda chunk: chunk.chunk_id))
        self.metadata = reader.metadata
        self._probe: sqlite3.Connection | None = sqlite3.connect(":memory:")
        self._probe.execute("CREATE VIRTUAL TABLE terms USING fts5(text, tokenize='unicode61')")
        self._probe.execute("CREATE VIRTUAL TABLE vocabulary USING fts5vocab(terms, 'row')")

    def _expression(self, question: str) -> str:
        if self._probe is None:
            raise LexicalRetrievalError("lexical_closed")
        try:
            with self._probe:
                self._probe.execute("DELETE FROM terms")
                self._probe.execute("INSERT INTO terms(text) VALUES (?)", (question,))
                terms = [row[0] for row in self._probe.execute("SELECT term FROM vocabulary ORDER BY term")]
                self._probe.execute("DELETE FROM terms")
            return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        except sqlite3.Error:
            raise LexicalRetrievalError("lexical_query") from None

    def search(self, question: str, k: int = 10) -> tuple[LexicalResult, ...]:
        validate_query(question, k)
        connection = self._reader._connection
        if connection is None:
            raise LexicalRetrievalError("lexical_closed")
        try:
            expression = self._expression(question)
            scores = {row[0]: float(row[1]) for row in connection.execute(
                "SELECT chunk_id, bm25(chunk_fts, 0.0, 1.0, 1.0, 1.0) FROM chunk_fts WHERE chunk_fts MATCH ?",
                (expression,))} if expression else {}
            if any(not math.isfinite(score) for score in scores.values()):
                raise LexicalRetrievalError("lexical_query")
            literals = extract_literals(question)
            candidates = []
            for chunk in self.chunks:
                matches = literal_matches(chunk, literals)
                if matches or chunk.chunk_id in scores:
                    candidates.append(LexicalResult(0, scores.get(chunk.chunk_id), chunk, matches))
            candidates.sort(key=lambda result: (not bool(result.literal_matches),
                                                -len({match.literal for match in result.literal_matches}),
                                                result.bm25_score is None,
                                                result.bm25_score if result.bm25_score is not None else 0.0,
                                                result.chunk.chunk_id))
            return tuple(LexicalResult(rank, result.bm25_score, result.chunk, result.literal_matches)
                         for rank, result in enumerate(candidates[:k], 1))
        except (sqlite3.Error, ValueError, TypeError) as error:
            if isinstance(error, LexicalRetrievalError):
                raise
            raise LexicalRetrievalError("lexical_query") from None

    def close(self) -> None:
        probe = getattr(self, "_probe", None)
        if probe is not None:
            probe.close()
            self._probe = None
        self._reader.close()

    def __enter__(self) -> "LexicalIndex":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ArgumentParser(description="Query an offline lexical snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    query = sub.add_parser("query")
    query.add_argument("--index", type=Path, required=True)
    query.add_argument("--question", required=True)
    query.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        with LexicalIndex(args.index) as index:
            report = [result.to_dict() for result in index.search(args.question, args.top_k)]
    except (StorageError, LexicalStorageError, LexicalRetrievalError) as error:
        print(f"lexical: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
