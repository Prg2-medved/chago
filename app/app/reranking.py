"""Explicit opt-in protocol-v2 CPU cross-encoder; legacy retrieval stays separate."""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from importlib import import_module
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

from app.config import EmbeddingSettings, RetrievalSettings
from app.embeddings import LocalEncoder
from app.evaluation import read_json
from app.hybrid_retrieval import HybridIndex, HybridResult
from app.index_storage import StoredChunk
from app.retrieval_evaluation import evaluate, protocol_input


SETTINGS = RetrievalSettings(120, 1, 60, 6)


class RerankingError(ValueError):
    """Controlled failure; never falls back to RRF or network loading."""


def manifest() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("reranker_manifest.json").read_text())


def verify_assets(path: Path) -> dict[str, Any]:
    expected = manifest()
    try:
        if {p.name for p in path.iterdir()} != set(expected["assets_sha256"]):
            raise RerankingError("reranker_assets")
        for name, digest in expected["assets_sha256"].items():
            with (path / name).open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                    raise RerankingError("reranker_assets")
        if any(version(name) != pinned for name, pinned in (
            ("torch", "2.7.1+cpu"), ("transformers", "4.57.3"), ("tokenizers", "0.22.2")
        )):
            raise RerankingError("reranker_runtime")
    except (OSError, ValueError):
        raise RerankingError("reranker_assets_or_runtime") from None
    return {**expected, "policy": "full-pair-cpu-fp32-v2", "score": "raw_classification_logit",
            "batch_size": 1, "padding": False, "truncation": False,
            "question_limit": 128, "pair_limit": 512}


class LocalCrossEncoder:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.identity = verify_assets(self.path)
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
            os.environ[name] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        try:
            backend = import_module("transformers")
            self.tokenizer = backend.AutoTokenizer.from_pretrained(
                str(self.path), use_fast=True, local_files_only=True, trust_remote_code=False)
            if not self.tokenizer.is_fast or self.tokenizer.num_special_tokens_to_add(pair=True) != 4:
                raise RerankingError("reranker_tokenizer")
            self.torch = import_module("torch")
            if self.torch.version.cuda is not None:
                raise RerankingError("reranker_runtime")
            self.torch.manual_seed(0)
            self.torch.use_deterministic_algorithms(True)
            self.torch.set_num_threads(4)
            self.torch.set_num_interop_threads(1)
        except Exception:
            raise RerankingError("reranker_initialization") from None
        self._model: Any = None
        self.model_loading_seconds = 0.0

    def pair(self, question: str, text: str) -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip():
            raise RerankingError("reranker_question")
        ids = self.tokenizer(question, add_special_tokens=False, padding=False, truncation=False)["input_ids"]
        if len(ids) > 128:
            raise RerankingError("reranker_question_budget")
        passage = self.tokenizer(text, add_special_tokens=False, padding=False, truncation=False)["input_ids"]
        pair = self.tokenizer(question, text, padding=False, truncation=False)
        if (pair["input_ids"] != self.tokenizer.build_inputs_with_special_tokens(ids, passage)
                or len(pair["input_ids"]) != len(ids) + len(passage) + 4):
            raise RerankingError("reranker_pair_framing")
        if len(pair["input_ids"]) > 512:
            raise RerankingError("reranker_pair_budget")
        return dict(pair)

    def preflight(self, question: str, chunks: Sequence[StoredChunk]) -> list[dict[str, Any]]:
        return [{"chunk_id": chunk.chunk_id, "tokens": len(self.pair(question, chunk.search_text)["input_ids"]),
                 "input_sha256": hashlib.sha256(json.dumps([question, chunk.search_text], ensure_ascii=False,
                                                           separators=(",", ":")).encode()).hexdigest()}
                for chunk in sorted(chunks, key=lambda chunk: chunk.chunk_id)]

    def _load(self) -> Any:
        if self._model is None:
            timer = perf_counter()
            try:
                backend = import_module("transformers")
                model = backend.AutoModelForSequenceClassification.from_pretrained(
                    str(self.path), local_files_only=True, trust_remote_code=False,
                    use_safetensors=True, dtype=self.torch.float32, attn_implementation="eager").cpu().eval()
                if model.config.num_labels != 1 or any(
                    p.dtype != self.torch.float32 or p.device.type != "cpu" for p in model.parameters()
                ):
                    raise RerankingError("reranker_model")
                self._model = model
            except Exception:
                raise RerankingError("reranker_model") from None
            self.model_loading_seconds = perf_counter() - timer
        return self._model

    def score(self, question: str, chunks: Sequence[StoredChunk]) -> dict[str, float]:
        self.preflight(question, chunks)
        scores = {}
        try:
            model = self._load()
            with self.torch.inference_mode():
                for chunk in sorted(chunks, key=lambda chunk: chunk.chunk_id):
                    # One complete pair at its actual length: no batch padding or truncation.
                    pair = self.pair(question, chunk.search_text)
                    inputs = {key: self.torch.tensor([value], device="cpu") for key, value in pair.items()}
                    logits = model(**inputs).logits
                    if tuple(logits.shape) != (1, 1):
                        raise RerankingError("reranker_logits")
                    value = float(logits[0, 0])
                    if not math.isfinite(value):
                        raise RerankingError("reranker_nonfinite")
                    scores[chunk.chunk_id] = value
        except RerankingError:
            raise
        except Exception:
            raise RerankingError("reranker_inference") from None
        return scores


@dataclass(frozen=True)
class RerankedResult:
    rank: int
    score: float
    original: HybridResult
    identity: dict[str, Any]

    @property
    def chunk(self) -> StoredChunk:
        return self.original.chunk

    def to_dict(self) -> dict[str, Any]:
        return {**self.original.to_dict(), "rank": self.rank, "reranker_score": self.score,
                "ranking_mode": "cross_encoder_v2", "reranker_identity": self.identity}


def rerank(question: str, candidates: Sequence[HybridResult], scorer: LocalCrossEncoder,
           k: int) -> tuple[RerankedResult, ...]:
    if type(k) is not int or k < 1:
        raise RerankingError("reranker_k")
    unique = {result.chunk.chunk_id: result for result in candidates}
    if len(unique) > 121:
        raise RerankingError("reranker_union_limit")
    scores = scorer.score(question, [unique[key].chunk for key in sorted(unique)])
    if set(scores) != set(unique) or any(not math.isfinite(score) for score in scores.values()):
        raise RerankingError("reranker_scores")
    ordered = sorted(unique, key=lambda key: (-scores[key], key))
    return tuple(RerankedResult(rank, scores[key], unique[key], scorer.identity)
                 for rank, key in enumerate(ordered[:k], 1))


class RerankedIndex:
    def __init__(self, base: HybridIndex, scorer: LocalCrossEncoder) -> None:
        if base.settings != SETTINGS:
            raise RerankingError("reranker_settings")
        if (base.snapshot.algorithm_version != "markdown-chunking-1"
                or base.metadata["lexical"]["literal_policy_version"] != 1):
            raise RerankingError("reranker_snapshot_policy")
        self.base, self.scorer = base, scorer
        self.snapshot, self.chunks = base.snapshot, base.chunks
        self.metadata = {**base.metadata, "reranker": scorer.identity}
        self.last_branch_union: tuple[StoredChunk, ...] = ()
        self.last_candidates: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []

    def search(self, question: str, k: int = 6) -> tuple[RerankedResult, ...]:
        if type(k) is not int or k < 1:
            raise RerankingError("reranker_k")
        candidates = self.base.search(question, 121)
        self.last_branch_union = self.base.last_branch_union
        timer = perf_counter()
        results = rerank(question, candidates, self.scorer, 121)
        self.last_rerank_seconds = perf_counter() - timer
        self.last_candidates = [{"chunk_id": result.chunk.chunk_id, "rank": result.rank,
                                 "reranker_score": result.score, "rrf_score": result.original.score,
                                 "semantic_rank": result.original.semantic_rank,
                                 "cosine_score": result.original.cosine_score,
                                 "lexical_rank": result.original.lexical_rank,
                                 "bm25_score": result.original.bm25_score,
                                 "source_ranges": result.chunk.source_ranges}
                                for result in results]
        self.trace.append({"question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                           "inputs": self.scorer.preflight(question, self.last_branch_union),
                           "candidates": self.last_candidates, "rerank_seconds": self.last_rerank_seconds})
        return results[:k]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit opt-in protocol-v2 offline reranking")
    parser.add_argument("command", choices=("query", "evaluate", "preflight"))
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True, help="Local E5 bundle")
    parser.add_argument("--reranker-path", type=Path, required=True)
    parser.add_argument("--question")
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--synthetic-index", type=Path)
    parser.add_argument("--split", choices=("tuning",), default="tuning")
    args = parser.parse_args(argv)
    try:
        scorer = LocalCrossEncoder(args.reranker_path)
        from contextlib import ExitStack
        with ExitStack() as stack:
            encoder = LocalEncoder(EmbeddingSettings(args.model_path))
            base = stack.enter_context(HybridIndex(args.index, encoder, SETTINGS))
            index = RerankedIndex(base, scorer)
            if args.command == "query":
                report: Any = [result.to_dict() for result in index.search(args.question)]
            else:
                if not all((args.questions, args.manifest, args.snapshot, args.fixtures, args.synthetic_index)):
                    raise RerankingError("reranker_evaluation_inputs")
                synthetic_base = stack.enter_context(HybridIndex(args.synthetic_index, encoder, SETTINGS))
                synthetic = RerankedIndex(synthetic_base, scorer)
                corpus, _ = read_json(args.questions, "questions")
                if not isinstance(corpus, dict) or not isinstance(corpus["questions"], list):
                    raise RerankingError("reranker_corpus")
                cases = [case for case in corpus["questions"] if isinstance(case, dict)
                         and case["split"] == "tuning"]
                preflight = []
                for case in cases:
                    question = protocol_input(case)
                    case_base = base if case["source_set"] == "live" else synthetic_base
                    candidates = case_base.search(question, 121)
                    preflight.append({"id": case["id"], "pairs": scorer.preflight(
                        question, [result.chunk for result in candidates])})
                if args.command == "preflight":
                    report = {"mode": "cross_encoder_v2_preflight", "cases": preflight}
                else:
                    report = evaluate(args.questions, args.manifest, args.snapshot, index, args.fixtures, synthetic,
                                      index_paths={"live": args.index, "synthetic": args.synthetic_index}, split=args.split,
                                      runtime_metadata={name: {"reranker": scorer.identity} for name in ("live", "synthetic")})
                    report.update(mode="cross_encoder_v2", effective_settings=vars(SETTINGS), preflight=preflight,
                                  reranker_trace={"live": index.trace, "synthetic": synthetic.trace})
        print(json.dumps(report, ensure_ascii=True, allow_nan=False))
        return 0
    except Exception as error:
        print(f"reranking: {error}" if isinstance(error, RerankingError) else "reranking: execution", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
