"""Frozen corpus protocol v1, separate from ordinary question-only retrieval."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
from typing import Any, cast

from app.evaluation import ValidationError, read_json, validate_package
from app.retrieval import SearchResult, SemanticIndex


PROTOCOL_VERSION = 1


def _hash_inputs(inputs: dict[str, Path]) -> dict[str, str]:
    try:
        return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()}
    except OSError:
        raise ValidationError("file: evaluation inputs") from None


def peak_memory_bytes() -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = wintypes.HANDLE
        measure = ctypes.windll.psapi.GetProcessMemoryInfo
        measure.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        measure.restype = wintypes.BOOL
        if not measure(process(), ctypes.byref(counters), counters.cb):
            raise ValidationError("runtime: peak memory")
        return int(counters.PeakWorkingSetSize)
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def protocol_input(case: dict[str, Any]) -> str:
    if "follow_up" in case["tags"]:
        return case["previous_question"] + "\n" + case["question"]
    return case["question"]


def covers(ranges: list[tuple[int, int]], start: int, end: int) -> bool:
    cursor = start
    for left, right in sorted(ranges):
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return False


def evidence_hit(case: dict[str, Any], results: tuple[SearchResult, ...], source: str) -> bool:
    ranges: dict[int, list[tuple[int, int]]] = {}
    for result in results[:5]:
        chunk = result.chunk
        if chunk.source == source:
            ranges.setdefault(chunk.document.page_id, []).extend(chunk.source_ranges)
    return bool(case["evidence"]) and all(
        covers(ranges.get(evidence["page_id"], []), span["start"], span["end"])
        for evidence in case["evidence"] for span in evidence["spans"]
    )


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    hits = [case["id"] for case in cases if case["hit"]]
    misses = [case["id"] for case in cases if not case["hit"]]
    return {"count": len(cases), "hits": len(hits), "misses": len(misses),
            "hit_at_5": len(hits) / len(cases) if cases else None,
            "hit_ids": hits, "miss_ids": misses}


def evaluate(questions: Path, manifest: Path, snapshot: Path, live: SemanticIndex,
             fixtures: Path | None = None, synthetic: SemanticIndex | None = None,
             index_paths: dict[str, Path] | None = None) -> dict[str, Any]:
    inputs = {"questions": questions, "manifest": manifest, "live_reference": snapshot}
    if fixtures is not None:
        inputs["synthetic_reference"] = fixtures
    if index_paths is not None:
        inputs.update({f"{key}_index": value for key, value in index_paths.items()})
    hashes = _hash_inputs(inputs)
    integrity = validate_package(questions, manifest, snapshot, fixtures)
    raw_corpus, _ = read_json(questions, "questions")
    corpus = cast(dict[str, Any], raw_corpus)
    indices = {"live": live}
    if fixtures is not None:
        if synthetic is None:
            raise ValidationError("index: synthetic required")
        indices["synthetic"] = synthetic
    for namespace, index in indices.items():
        reference_path = snapshot if namespace == "live" else fixtures
        assert reference_path is not None
        raw_reference, _ = read_json(reference_path, namespace)
        reference = cast(dict[str, Any], raw_reference)
        expected = {doc["page_id"]: doc for doc in reference["documents"]}
        actual = {doc.page_id: asdict(doc) for doc in index.snapshot.documents}
        if index.snapshot.source != reference["source"] or actual != expected:
            raise ValidationError(f"index: {namespace} inventory")
        if index.snapshot.settings != {"target": 350, "maximum": 450, "overlap": 50, "input_limit": 512}:
            raise ValidationError(f"index: {namespace} settings")
    cases = []
    for case in corpus["questions"]:
        index = indices[case["source_set"]]
        timer = perf_counter()
        results = index.search(protocol_input(case), 5)
        duration = perf_counter() - timer
        answerable = case["answerable"]
        cases.append({"id": case["id"], "source_set": case["source_set"], "split": case["split"],
                      "follow_up": "follow_up" in case["tags"], "answerable": answerable,
                      "expected_behavior": case["expected_behavior"],
                      "hit": evidence_hit(case, results, index.snapshot.source) if answerable else None,
                      "ranking": [{"chunk_id": result.chunk.chunk_id, "score": result.score} for result in results],
                      "duration_seconds": duration})
    groups: dict[str, dict[str, Any]] = {}
    for namespace in ("live", "synthetic"):
        groups[namespace] = {}
        for split in ("tuning", "holdout"):
            selected = [case for case in cases if case["source_set"] == namespace and case["split"] == split]
            groups[namespace][split] = {
                "single_question": _metrics([case for case in selected if case["answerable"] and not case["follow_up"]]),
                "follow_up": {"protocol_version": PROTOCOL_VERSION, **_metrics([case for case in selected if case["answerable"] and case["follow_up"]])},
                "refuse": [case["id"] for case in selected if case["expected_behavior"] == "refuse"],
                "clarify": [case["id"] for case in selected if case["expected_behavior"] == "clarify"],
            }
    after = _hash_inputs(inputs)
    if hashes != after:
        raise ValidationError("fingerprint: inputs changed")
    return {"protocol_version": PROTOCOL_VERSION, "corpus_version": integrity.corpus_version,
            "environment": {"platform": platform.platform(), "processor": platform.processor(),
                            "python": platform.python_version()},
            "fingerprints": hashes, "reference_fingerprints": integrity.fingerprints,
            "indices": {name: {"identity": index.metadata, "chunk_settings": index.snapshot.settings,
                               "algorithm_version": index.snapshot.algorithm_version,
                               "batch_size": index.encoder.settings.batch_size,
                               "cpu_threads": index.encoder.settings.cpu_threads,
                               "documents": len(index.snapshot.documents), "chunks": len(index.chunks)}
                        for name, index in indices.items()},
            "groups": groups, "cases": cases, "peak_memory_bytes": peak_memory_bytes()}
