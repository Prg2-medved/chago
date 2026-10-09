"""Consistent read-only semantic/lexical branches and deterministic RRF."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from app.config import RetrievalSettings, load_embedding_settings, load_retrieval_settings
from app.embeddings import EmbeddingError, LocalEncoder
from app.evaluation import ValidationError
from app.index_storage import StorageError, StoredChunk
from app.lexical_retrieval import LexicalIndex, LexicalResult, LexicalRetrievalError, LiteralMatch
from app.lexical_storage import LexicalReader, LexicalStorageError
from app.retrieval import RetrievalError, SearchResult, SemanticIndex, _ArgumentParser
from app.semantic_storage import SemanticReader, SemanticStorageError


class HybridRetrievalError(ValueError):
    """Safe category; failed branches never fall back silently."""


@dataclass(frozen=True)
class HybridResult:
    rank: int
    score: float
    chunk: StoredChunk
    semantic_rank: int | None
    cosine_score: float | None
    lexical_rank: int | None
    bm25_score: float | None
    literal_matches: tuple[LiteralMatch, ...]

    def to_dict(self) -> dict[str, Any]:
        chunk = asdict(self.chunk)
        document = chunk.pop("document")
        document.pop("markdown")
        return {"rank": self.rank, "rrf_score": self.score,
                "semantic_rank": self.semantic_rank, "cosine_score": self.cosine_score,
                "lexical_rank": self.lexical_rank, "bm25_score": self.bm25_score,
                "literal_matches": [asdict(match) for match in self.literal_matches], **document, **chunk}


def fuse(semantic: tuple[SearchResult, ...], lexical: tuple[LexicalResult, ...],
         constant: int, k: int) -> tuple[HybridResult, ...]:
    if any(type(value) is not int or value < 1 for value in (constant, k)):
        raise HybridRetrievalError("hybrid_configuration")
    sem = {result.chunk.chunk_id: result for result in semantic}
    lex = {result.chunk.chunk_id: result for result in lexical}
    combined = []
    for chunk_id in sorted(sem.keys() | lex.keys()):
        s, l = sem.get(chunk_id), lex.get(chunk_id)
        chunk = s.chunk if s is not None else lex[chunk_id].chunk
        score = (1 / (constant + s.rank) if s is not None else 0) + (1 / (constant + l.rank) if l is not None else 0)
        combined.append(HybridResult(0, score, chunk, s.rank if s else None, s.score if s else None,
                                     l.rank if l else None, l.bm25_score if l else None, l.literal_matches if l else ()))
    combined.sort(key=lambda result: (-result.score, result.chunk.chunk_id))
    return tuple(replace(result, rank=rank) for rank, result in enumerate(combined[:k], 1))


class HybridIndex:
    def __init__(self, path: Path, encoder: LocalEncoder, settings: RetrievalSettings | None = None) -> None:
        self.settings = settings if settings is not None else RetrievalSettings()
        if not isinstance(self.settings, RetrievalSettings):
            raise HybridRetrievalError("hybrid_configuration")
        self.settings.__post_init__()
        self._reader = LexicalReader(path)
        self._lexical: LexicalIndex | None = None
        try:
            reader = SemanticReader._from_base(self._reader)
            self._semantic = SemanticIndex._from_reader(reader, encoder)
            self._lexical = LexicalIndex._from_reader(self._reader)
            self.encoder = encoder
            self.snapshot = reader.snapshot
            self.chunks = reader.chunks
            self.metadata = {"semantic": reader.metadata, "lexical": self._reader.metadata}
        except BaseException:
            self.close()
            raise

    def search(self, question: str, k: int | None = None) -> tuple[HybridResult, ...]:
        final_k = self.settings.top_k if k is None else k
        if type(final_k) is not int or final_k < 1:
            raise HybridRetrievalError("hybrid_k")
        if self._reader._connection is None or self._lexical is None:
            raise HybridRetrievalError("hybrid_closed")
        try:
            semantic = self._semantic.search(question, self.settings.semantic_candidates)
            lexical = self._lexical.search(question, self.settings.lexical_candidates)
            return fuse(semantic, lexical, self.settings.rrf_constant, final_k)
        except (StorageError, SemanticStorageError, EmbeddingError, RetrievalError,
                LexicalStorageError, LexicalRetrievalError, HybridRetrievalError):
            raise
        except Exception:
            raise HybridRetrievalError("hybrid_branch") from None

    def close(self) -> None:
        if self._lexical is not None:
            self._lexical.close()
            self._lexical = None
        self._reader.close()

    def __enter__(self) -> "HybridIndex":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ArgumentParser(description="Query or compare offline hybrid retrieval")
    sub = parser.add_subparsers(dest="command", required=True)
    query = sub.add_parser("query")
    query.add_argument("--index", type=Path, required=True)
    query.add_argument("--question", required=True)
    query.add_argument("--model-path", type=Path)
    for flag in ("semantic-candidates", "lexical-candidates", "rrf-constant", "top-k"):
        query.add_argument(f"--{flag}", type=int)
    from app.retrieval_comparison import add_arguments, compare
    evaluation = sub.add_parser("evaluate")
    add_arguments(evaluation)
    args = parser.parse_args(argv)
    try:
        settings = load_retrieval_settings(semantic_candidates=args.semantic_candidates, lexical_candidates=args.lexical_candidates,
                                           rrf_constant=args.rrf_constant, top_k=args.top_k)
        report: Any
        if args.command == "evaluate":
            report = compare(args, settings)
        else:
            embedding = load_embedding_settings()
            if args.model_path is not None:
                embedding = replace(embedding, model_path=args.model_path)
            with HybridIndex(args.index, LocalEncoder(embedding), settings) as index:
                report = [result.to_dict() for result in index.search(args.question)]
    except (StorageError, SemanticStorageError, EmbeddingError, RetrievalError, LexicalStorageError,
            LexicalRetrievalError, HybridRetrievalError, ValidationError) as error:
        print(f"hybrid: {error}", file=sys.stderr)
        return 1
    except (ValueError, OSError, sqlite3.Error):
        print("hybrid: configuration", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
