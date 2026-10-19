"""Frozen corpus protocol v1, separate from ordinary question-only retrieval."""

from dataclasses import asdict
from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.evaluation import ValidationError, read_json, validate_package
from app.index_storage import StorageSnapshot, StoredChunk

if TYPE_CHECKING:
    from app.retrieval import SemanticIndex


PROTOCOL_VERSION = 1


class RankedResult(Protocol):
    @property
    def rank(self) -> int: ...
    @property
    def chunk(self) -> StoredChunk: ...


class SearchIndex(Protocol):
    @property
    def snapshot(self) -> StorageSnapshot: ...
    @property
    def chunks(self) -> tuple[StoredChunk, ...]: ...
    @property
    def metadata(self) -> dict[str, Any]: ...
    def search(self, question: str, k: int = 10) -> Sequence[RankedResult]: ...


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


def evidence_hit(case: dict[str, Any], results: Sequence[RankedResult], source: str) -> bool:
    ranges: dict[int, list[tuple[int, int]]] = {}
    for result in results[:5]:
        chunk = result.chunk
        if chunk.source == source:
            ranges.setdefault(chunk.document.page_id, []).extend(chunk.source_ranges)
    return bool(case["evidence"]) and all(
        covers(ranges.get(evidence["page_id"], []), span["start"], span["end"])
        for evidence in case["evidence"] for span in evidence["spans"]
    )


def source_cover(case: dict[str, Any], chunks: Sequence[StoredChunk], source: str,
                 *, max_states: int = 100000) -> dict[str, Any]:
    """Exact bounded set cover over original evidence intervals, never generated text."""
    atoms: list[tuple[int, int, int]] = []
    eligible: dict[int, list[tuple[StoredChunk, list[tuple[int, int]]]]] = {}
    for evidence in case["evidence"]:
        page = evidence["page_id"]
        entries = []
        for chunk in chunks:
            if chunk.source != source or chunk.document.page_id != page:
                continue
            if any(getattr(chunk.document, key) != evidence[key]
                   for key in ("locale", "path", "content_sha256") if key in evidence):
                continue
            ranges = [(max(left, segment["start"]), min(right, segment["end"]))
                      for left, right in chunk.source_ranges for segment in chunk.segments
                      if segment["kind"] == "source"
                      and max(left, segment["start"]) < min(right, segment["end"])]
            entries.append((chunk, ranges))
        eligible[page] = entries
        for span in evidence["spans"]:
            start, end = span["start"], span["end"]
            endpoints = sorted({start, end} | {point for _, ranges in entries
                                              for pair in ranges for point in pair if start < point < end})
            atoms.extend((page, left, right) for left, right in zip(endpoints, endpoints[1:]))
    masks: dict[int, StoredChunk] = {}
    for page, entries in eligible.items():
        for chunk, ranges in entries:
            mask = sum(1 << i for i, (p, left, right) in enumerate(atoms)
                       if p == page and covers(ranges, left, right))
            if mask and (mask not in masks or chunk.chunk_id < masks[mask].chunk_id):
                masks[mask] = chunk
    full = (1 << len(atoms)) - 1
    union = 0
    for mask in masks:
        union |= mask
    missing = [{"page_id": page, "start": left, "end": right}
               for i, (page, left, right) in enumerate(atoms) if not union & (1 << i)]
    if not full or union != full:
        return {"covered": False, "status": "impossible", "minimum": None,
                "lower_bound": None, "upper_bound": None, "witness": [], "missing_ranges": missing}
    # A mask contained in another cannot improve the minimum cardinality.
    options = sorted((mask for mask in masks if not any(mask != other and mask | other == other for other in masks)),
                     key=lambda mask: masks[mask].chunk_id)
    greedy: list[int] = []
    covered = 0
    while covered != full:
        best = max(options, key=lambda mask: (mask & ~covered).bit_count())
        covered |= best
        greedy.append(best)
    lower = (len(atoms) + max(mask.bit_count() for mask in options) - 1) // max(mask.bit_count() for mask in options)
    witness = greedy
    minimum: int | None = None
    states = 0
    frontier: dict[int, list[int]] = {0: []}
    seen = {0}
    for depth in range(1, len(greedy) + 1):
        next_frontier: dict[int, list[int]] = {}
        exhausted = False
        for covered, path in frontier.items():
            for mask in options:
                states += 1
                if states > max_states:
                    exhausted = True
                    break
                merged = covered | mask
                if merged == full:
                    witness, minimum = [*path, mask], depth
                    break
                if merged not in seen:
                    seen.add(merged)
                    next_frontier[merged] = [*path, mask]
            if exhausted or minimum is not None:
                break
        if exhausted or minimum is not None:
            break
        lower = max(lower, depth + 1)
        frontier = next_frontier
    return {"covered": True, "status": "exact" if minimum is not None else "unknown",
            "minimum": minimum, "lower_bound": minimum if minimum is not None else lower,
            "upper_bound": len(witness), "states": states, "missing_ranges": [],
            "witness": [{"chunk_id": masks[mask].chunk_id,
                         "page_id": masks[mask].document.page_id,
                         "source_ranges": [list(pair) for pair in masks[mask].source_ranges]} for mask in witness]}


def retrieval_diagnostics(case: dict[str, Any], inventory: Sequence[StoredChunk],
                          branch_union: Sequence[StoredChunk], results: Sequence[RankedResult],
                          source: str) -> dict[str, Any]:
    inventory_cover = source_cover(case, inventory, source)
    branch = source_cover(case, branch_union, source)
    final = source_cover(case, [result.chunk for result in results[:5]], source)
    return {"inventory": inventory_cover, "branch_union": branch, "final_top_5": final,
            "candidate_loss": inventory_cover["covered"] and not branch["covered"],
            "ranking_loss": branch["covered"] and not final["covered"]}


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    hits = [case["id"] for case in cases if case["hit"]]
    misses = [case["id"] for case in cases if not case["hit"]]
    return {"count": len(cases), "hits": len(hits), "misses": len(misses),
            "hit_at_5": len(hits) / len(cases) if cases else None,
            "hit_ids": hits, "miss_ids": misses}


def evaluate(questions: Path, manifest: Path, snapshot: Path, live: SearchIndex,
             fixtures: Path | None = None, synthetic: SearchIndex | None = None,
             index_paths: dict[str, Path] | None = None, *, split: str = "all",
             runtime_metadata: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if split not in {"all", "tuning", "holdout"}:
        raise ValidationError("evaluation: split")
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
        if split != "all" and case["split"] != split:
            continue
        index = indices[case["source_set"]]
        timer = perf_counter()
        results = index.search(protocol_input(case), 5)
        duration = perf_counter() - timer
        answerable = case["answerable"]
        cases.append({"id": case["id"], "source_set": case["source_set"], "split": case["split"],
                      "follow_up": "follow_up" in case["tags"], "answerable": answerable,
                      "expected_behavior": case["expected_behavior"],
                      "hit": evidence_hit(case, results, index.snapshot.source) if answerable else None,
                      "ranking": [{"chunk_id": result.chunk.chunk_id,
                                   "score": getattr(result, "score", getattr(result, "bm25_score", None))}
                                  for result in results],
                      "duration_seconds": duration,
                      "diagnostics": retrieval_diagnostics(
                          case, index.chunks, getattr(index, "last_branch_union", tuple(result.chunk for result in results)),
                          results, index.snapshot.source) if answerable else None})
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
    def runtime(name: str, index: SearchIndex) -> dict[str, Any]:
        if runtime_metadata is not None:
            return runtime_metadata[name]
        # Preserve the existing semantic report when no explicit adapter metadata is supplied.
        semantic = cast("SemanticIndex", index)
        return {"batch_size": semantic.encoder.settings.batch_size,
                "cpu_threads": semantic.encoder.settings.cpu_threads}
    return {"protocol_version": PROTOCOL_VERSION, "corpus_version": integrity.corpus_version,
            "environment": {"platform": platform.platform(), "processor": platform.processor(),
                            "python": platform.python_version()},
            "fingerprints": hashes, "reference_fingerprints": integrity.fingerprints,
            "indices": {name: {"identity": index.metadata, "chunk_settings": index.snapshot.settings,
                               "algorithm_version": index.snapshot.algorithm_version,
                               **runtime(name, index),
                               "documents": len(index.snapshot.documents), "chunks": len(index.chunks)}
                        for name, index in indices.items()},
            "groups": groups, "cases": cases, "peak_memory_bytes": peak_memory_bytes()}
