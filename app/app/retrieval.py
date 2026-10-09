"""Exact cosine search over one self-contained semantic snapshot."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import sys
from typing import Any, Never

from app.config import load_embedding_settings
from app.evaluation import ValidationError
from app.embeddings import EmbeddingError, LocalEncoder
from app.index_storage import StorageError, StoredChunk
from app.semantic_storage import SemanticReader, SemanticStorageError


class RetrievalError(ValueError):
    """Safe retrieval error category."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "retrieval: arguments\n")


@dataclass(frozen=True)
class SearchResult:
    rank: int
    score: float
    chunk: StoredChunk

    def to_dict(self) -> dict[str, Any]:
        chunk = asdict(self.chunk)
        document = chunk.pop("document")
        document.pop("markdown")
        return {"rank": self.rank, "score": self.score, **document, **chunk}


class SemanticIndex:
    def __init__(self, path: Path, encoder: LocalEncoder) -> None:
        reader = SemanticReader(path)
        if any(reader.metadata.get(key) != value for key, value in encoder.identity.items()):
            raise RetrievalError("retrieval_identity_rebuild")
        self.encoder = encoder
        self.snapshot = reader.snapshot
        self.metadata = reader.metadata
        self.chunks = reader.chunks
        self.matrix = reader.matrix

    def search(self, question: str, k: int = 10) -> tuple[SearchResult, ...]:
        if type(k) is not int or k < 1:
            raise RetrievalError("retrieval_k")
        # Even an empty index validates the supplied question and budget.
        query = self.encoder.encode_query(question)
        scores = self.matrix @ query
        order = sorted(range(len(self.chunks)), key=lambda index: (-float(scores[index]), self.chunks[index].chunk_id))
        return tuple(SearchResult(rank, float(scores[index]), self.chunks[index])
                     for rank, index in enumerate(order[:k], 1))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ArgumentParser(description="Query an offline semantic snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    query = sub.add_parser("query")
    query.add_argument("--index", type=Path, required=True)
    query.add_argument("--model-path", type=Path)
    query.add_argument("--question", required=True)
    query.add_argument("--top-k", type=int, default=10)
    evaluation = sub.add_parser("evaluate")
    for name in ("questions", "manifest", "snapshot", "index"):
        evaluation.add_argument(f"--{name}", type=Path, required=True)
    for name in ("fixtures", "synthetic-index", "model-path"):
        evaluation.add_argument(f"--{name}", type=Path)
    args = parser.parse_args(argv)
    try:
        settings = load_embedding_settings()
        if args.model_path is not None:
            settings = replace(settings, model_path=args.model_path)
        index = SemanticIndex(args.index, LocalEncoder(settings))
        report: Any
        if args.command == "query":
            report = [result.to_dict() for result in index.search(args.question, args.top_k)]
        else:
            from app.retrieval_evaluation import evaluate
            if (args.fixtures is None) != (args.synthetic_index is None):
                raise ValidationError("index: synthetic inputs required")
            synthetic = SemanticIndex(args.synthetic_index, index.encoder) if args.synthetic_index is not None else None
            paths = {"live": args.index}
            if args.synthetic_index is not None:
                paths["synthetic"] = args.synthetic_index
            report = evaluate(args.questions, args.manifest, args.snapshot, index, args.fixtures, synthetic, paths)
    except (StorageError, SemanticStorageError, EmbeddingError, RetrievalError, ValidationError) as error:
        print(f"retrieval: {error}", file=sys.stderr)
        return 1
    except ValueError:
        print("retrieval: configuration", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
