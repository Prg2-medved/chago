"""Frozen three-mode comparison with isolated process memory/latency measurements."""

import argparse
from collections.abc import Sequence
from contextlib import ExitStack, closing
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from time import perf_counter
from typing import Any, Never

from app.config import RetrievalSettings, load_embedding_settings, load_retrieval_settings
from app.evaluation import ValidationError
from app.lexical_retrieval import LexicalIndex
from app.lexical_storage import LITERAL_POLICY_VERSION, QUERY_POLICY_VERSION
from app.retrieval_evaluation import SearchIndex, _hash_inputs, _metrics, evaluate, peak_memory_bytes


MODES = ("semantic", "lexical", "hybrid")


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "comparison: arguments\n")


def stable_results(report: dict[str, Any]) -> dict[str, Any]:
    return {"groups": report["groups"], "cases": [
        {key: value for key, value in case.items() if key not in {"duration_seconds", "warm_duration_seconds", "cold"}}
        for case in report["cases"]]}


def _load_mode(stack: ExitStack, mode: str, path: Path, settings: RetrievalSettings, encoder: Any) -> SearchIndex:
    if mode == "lexical":
        return stack.enter_context(LexicalIndex(path))
    # Heavy embedding modules are loaded exclusively in semantic/hybrid workers.
    if mode == "hybrid":
        from app.hybrid_retrieval import HybridIndex
        return stack.enter_context(HybridIndex(path, encoder, settings))
    from app.lexical_storage import LexicalReader
    from app.retrieval import SemanticIndex
    from app.semantic_storage import SemanticReader
    base = stack.enter_context(LexicalReader(path))
    return SemanticIndex._from_reader(SemanticReader._from_base(base), encoder)


def worker(args: argparse.Namespace, settings: RetrievalSettings) -> dict[str, Any]:
    timer = perf_counter()
    embedding = load_embedding_settings()
    if args.model_path is not None:
        embedding = replace(embedding, model_path=args.model_path)
    encoder = None
    if args.mode != "lexical":
        from app.embeddings import LocalEncoder
        encoder = LocalEncoder(embedding)
    with ExitStack() as stack:
        live = _load_mode(stack, args.mode, args.index, settings, encoder)
        synthetic = _load_mode(stack, args.mode, args.synthetic_index, settings, encoder) if args.synthetic_index is not None else None
        indices = {"live": args.index}
        if args.synthetic_index is not None:
            indices["synthetic"] = args.synthetic_index
        runtime = {name: ({"batch_size": embedding.batch_size, "cpu_threads": embedding.cpu_threads}
                          if args.mode != "lexical" else {"inference": False}) for name in indices}
        initialization = perf_counter() - timer
        report = evaluate(args.questions, args.manifest, args.snapshot, live, args.fixtures, synthetic, indices,
                          split=args.split, runtime_metadata=runtime)
        repeat = evaluate(args.questions, args.manifest, args.snapshot, live, args.fixtures, synthetic, indices,
                          split=args.split, runtime_metadata=runtime)
        if stable_results(report) != stable_results(repeat) or report["fingerprints"] != repeat["fingerprints"]:
            raise ValidationError("comparison: repeat mismatch")
        for position, (case, warm) in enumerate(zip(report["cases"], repeat["cases"], strict=True)):
            case["cold"] = position == 0
            case["warm_duration_seconds"] = warm["duration_seconds"]
        report.update(mode=args.mode, requested_split=args.split, effective_settings=asdict(settings),
                      embedding_settings={"batch_size": embedding.batch_size, "cpu_threads": embedding.cpu_threads},
                      policy_versions={"query": QUERY_POLICY_VERSION, "literal": LITERAL_POLICY_VERSION},
                      initialization_seconds=initialization, peak_memory_bytes=peak_memory_bytes(),
                      measurement={"process_isolation": True, "cold": "first query includes lazy model load; initialization separate",
                                   "warm": "second pass with retained indexes/encoder; no page-cache clearing",
                                   "peak": "Windows PeakWorkingSetSize; Unix ru_maxrss", "repeated_rankings_equal": True},
                      heavy_imports_loaded=sorted(name for name in ("numpy", "torch", "sentence_transformers", "transformers", "tokenizers")
                                                  if sys.modules.get(name) is not None))
        if args.mode == "lexical" and report["heavy_imports_loaded"]:
            raise ValidationError("comparison: lexical heavy imports")
        with closing(sqlite3.connect(":memory:")) as connection:
            report["environment"]["sqlite"] = {"version": sqlite3.sqlite_version,
                                                "compile_options": sorted(row[0] for row in connection.execute("PRAGMA compile_options"))}
        return report


def merge_reports(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if set(reports) != set(MODES):
        raise ValidationError("comparison: modes")
    first = reports["semantic"]
    keys = ("fingerprints", "reference_fingerprints", "effective_settings", "embedding_settings",
            "environment", "requested_split", "protocol_version", "corpus_version", "policy_versions")
    for mode, report in reports.items():
        if report["mode"] != mode or any(report[key] != first[key] for key in keys):
            raise ValidationError("comparison: incompatible reports")
        if [(case["id"], case["source_set"], case["split"]) for case in report["cases"]] != [
            (case["id"], case["source_set"], case["split"]) for case in first["cases"]]:
            raise ValidationError("comparison: incompatible cases")
    aggregates = {}
    for mode, report in reports.items():
        cases = [case for case in report["cases"] if case["source_set"] == "live" and case["answerable"] and not case["follow_up"]]
        aggregates[mode] = _metrics(cases)
    semantic = {case["id"]: case for case in first["cases"]}
    transitions = {}
    for mode in ("lexical", "hybrid"):
        transitions[mode] = {
            "semantic_miss_to_hit": [case["id"] for case in reports[mode]["cases"] if case["answerable"] and not semantic[case["id"]]["hit"] and case["hit"]],
            "semantic_hit_to_miss": [case["id"] for case in reports[mode]["cases"] if case["answerable"] and semantic[case["id"]]["hit"] and not case["hit"]],
        }
    hybrid = aggregates["hybrid"]
    return {"report_schema_version": 1, **{key: first[key] for key in keys},
            "modes": reports, "live_single_question": aggregates, "transitions": transitions,
            "holdout_exposure": "Holdout was already measured in the previous semantic baseline; this is not blind evaluation.",
            "quality_acceptance": {"target": .9, "measured_hit_at_5": hybrid["hit_at_5"], "miss_ids": hybrid["miss_ids"],
                                   "accepted": first["requested_split"] == "all" and hybrid["count"] > 0 and hybrid["hit_at_5"] >= .9}}


def compare(args: argparse.Namespace, settings: RetrievalSettings) -> dict[str, Any]:
    if (args.fixtures is None) != (args.synthetic_index is None):
        raise ValidationError("index: synthetic inputs required")
    inputs = {"questions": args.questions, "manifest": args.manifest, "live_reference": args.snapshot, "live_index": args.index}
    if args.fixtures is not None:
        inputs.update(synthetic_reference=args.fixtures, synthetic_index=args.synthetic_index)
    before = _hash_inputs(inputs)
    common = []
    for name in ("questions", "manifest", "snapshot", "index", "fixtures", "synthetic_index", "model_path"):
        value = getattr(args, name)
        if value is not None:
            common.extend(["--" + name.replace("_", "-"), str(value.resolve())])
    common.extend(["--split", args.split])
    for name, value in asdict(settings).items():
        common.extend(["--" + name.replace("_", "-"), str(value)])
    reports = {}
    environment = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    for mode in MODES:
        try:
            process = subprocess.run([sys.executable, "-m", "app.retrieval_comparison", "worker", "--mode", mode, *common],
                                     capture_output=True, encoding="utf-8", env=environment, timeout=600)
            if process.returncode != 0:
                raise ValidationError("comparison: worker failure")
            reports[mode] = json.loads(process.stdout)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            raise ValidationError("comparison: worker failure") from None
    merged = merge_reports(reports)
    if _hash_inputs(inputs) != before or merged["fingerprints"] != before:
        raise ValidationError("fingerprint: inputs changed")
    return merged


def add_arguments(parser: argparse.ArgumentParser) -> None:
    for name in ("questions", "manifest", "snapshot", "index"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("fixtures", "synthetic-index", "model-path"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("semantic-candidates", "lexical-candidates", "rrf-constant", "top-k"):
        parser.add_argument(f"--{name}", type=int)
    parser.add_argument("--split", choices=("tuning", "holdout", "all"), default="all")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ArgumentParser(description="Isolated frozen retrieval comparison")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluation = sub.add_parser("evaluate")
    add_arguments(evaluation)
    single = sub.add_parser("worker")
    add_arguments(single)
    single.add_argument("--mode", choices=MODES, required=True)
    args = parser.parse_args(argv)
    try:
        settings = load_retrieval_settings(semantic_candidates=args.semantic_candidates, lexical_candidates=args.lexical_candidates,
                                           rrf_constant=args.rrf_constant, top_k=args.top_k)
        report = worker(args, settings) if args.command == "worker" else compare(args, settings)
    except ValidationError as error:
        print(f"comparison: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("comparison: execution", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
