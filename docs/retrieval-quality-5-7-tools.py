"""Manual task 5.7 tools. No inference unless preflight/worker is explicitly invoked.

Uses the existing retrieval/scorer API; does not implement a ranking policy.
Run from the staged repository root. Outputs must be new files.
"""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tarfile
from time import perf_counter

E5 = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
CE = "1427fd652930e4ba29e8149678df786c240d8825"
RECEIPT = "docs/retrieval-quality-protocol-receipt-v2.json"
ARMS = ("legacy", "control", "reranker")
ROOT = Path.cwd()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def commitments():
    receipt = read(RECEIPT)
    expected = {receipt["protocol_path"]: receipt["protocol_sha256"]}
    expected.update({r["path"]: r["expected_sha256"] for r in receipt["protected_input_checks"]})
    expected.update(receipt["immutable_v1_artifact_sha256"])
    expected.update({r["path"]: r["sha256"] for r in receipt["v1_reports"]})
    expected.update(receipt["implementation_verification"]["files_sha256"])
    for model, filename in ((E5, "embedding_manifest.json"), (CE, "reranker_manifest.json")):
        assets = read(Path("app/app") / filename)["assets_sha256"]
        expected.update({f"data/models/{model}/{name}": digest for name, digest in assets.items()})
    for name, item in receipt["model_bundle_verification"]["files"].items():
        assert expected[f"data/models/{CE}/{name}"] == item["sha256"]
    assert len(receipt["v1_reports"]) == 36
    for name, digest in expected.items():
        assert sha(name) == digest, f"STOP SHA-256: {name}"
    return expected


def pack(destination):
    expected = commitments()
    paths = set(expected) | {RECEIPT, "compose.yaml", "app/Dockerfile", "app/requirements.txt",
                             "docs/retrieval-quality-5-7-tools.py", "docs/retrieval-quality-5-7-run.sh",
                             "docs/retrieval-quality-5-7-test.py", "docs/retrieval-quality-5-7-manual.md"}
    paths.update(p.as_posix() for p in Path("app/app").rglob("*") if p.suffix in {".py", ".json"})
    paths.update(p.as_posix() for p in Path("app/tests").glob("test_*.py"))
    paths.add("app/requirements-dev.txt")
    test_log = Path("data/retrieval-quality-improvement/reranker-v2/manual-local-checks.txt")
    assert test_log.is_file(), "STOP run local checks from the runbook before packing"
    paths.add(test_log.as_posix())
    manifest = {name: sha(name) for name in sorted(paths)}
    archive = Path(destination)
    assert not archive.exists() and not archive.with_suffix(".json").exists()
    with tarfile.open(archive, "x") as out:
        for name in sorted(paths):
            assert not Path(name).is_symlink(), name
            out.add(name, arcname=name, recursive=False)
    metadata = {"files": manifest, "archive_sha256": sha(archive),
                "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "git_status": subprocess.check_output(["git", "status", "--porcelain=v1"], text=True),
                "scope": "task 5.7 transport fingerprint; NOT acceptance lock"}
    write(archive.with_suffix(".json"), metadata)
    print(json.dumps({"archive": str(archive), "sha256": metadata["archive_sha256"], "files": len(paths)}))


def check(transport):
    expected = commitments()
    for name, digest in read(transport)["files"].items():
        assert sha(name) == digest, f"STOP transport: {name}"
    return {"passed": True, "protected_files": len(expected), "transport": sha(transport)}


def offline():
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ[name] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("blocked")
        raise RuntimeError("STOP network attempt")

    socket.socket.connect = socket.socket.connect_ex = deny
    socket.create_connection = socket.getaddrinfo = deny
    sys.path.insert(0, str(ROOT / "app"))
    return attempts


def cpu_identity(cpuinfo):
    # Explicit allowlist: frequency, bogomips and future diagnostic fields are not identities.
    fields = {"processor", "vendor_id", "cpu family", "model", "model name", "stepping", "microcode",
              "physical id", "core id", "cpu cores", "siblings", "cache size", "address sizes", "flags"}
    processors = []
    for block in cpuinfo.strip().split("\n\n"):
        identity = {}
        for line in block.splitlines():
            key, separator, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if separator and key in fields:
                identity[key] = sorted(value.split()) if key == "flags" else value
        if identity:
            assert "processor" in identity, "STOP incomplete CPU identity"
            processors.append(identity)
    assert processors, "STOP missing CPU identity"
    return sorted(processors, key=lambda item: int(item["processor"]))


def runtime():
    packages = {name: version(name) for name in
                ("torch", "transformers", "tokenizers", "sentence-transformers", "numpy", "safetensors")}
    for name, pin in (("torch", "2.7.1+cpu"), ("transformers", "4.57.3"), ("tokenizers", "0.22.2"),
                      ("sentence-transformers", "5.1.2"), ("numpy", "2.2.6")):
        assert packages[name] == pin, (name, packages[name], pin)
    cpuinfo = Path("/proc/cpuinfo").read_text()
    environment = {"packages": packages, "python": platform.python_version(),
                   "python_implementation": platform.python_implementation(),
                   "system": platform.system(), "kernel_release": platform.release(),
                   "kernel_version": platform.version(), "machine": platform.machine(),
                   "libc": platform.libc_ver(), "cpu": cpu_identity(cpuinfo)}
    diagnostics = {"cpuinfo": cpuinfo, "hostname": socket.gethostname()}
    return environment, diagnostics


def cg():
    root = Path("/sys/fs/cgroup")
    # Require cgroup v2 with authoritative peak and swap counters; no sampled-peak substitution.
    names = ("memory.max", "memory.peak", "memory.current", "memory.swap.max", "memory.swap.current",
             "memory.events", "cpu.max", "cpu.stat")
    values = {name: (root / name).read_text().strip() for name in names}
    assert values["memory.max"] == str(5 * 1024**3)
    assert values["memory.swap.max"] == "0"
    quota, period = map(int, values["cpu.max"].split())
    assert quota == 4 * period
    return values


def inputs():
    # Parse the frozen container, select tuning immediately; never inspect holdout cases/results.
    cases = [c for c in read("eval/questions.yaml")["questions"] if c["split"] == "tuning"]
    single = [c for c in cases if c["source_set"] == "live" and c["answerable"] and "follow_up" not in c["tags"]]
    assert len(single) == 9 and len(cases) == 14
    return cases


def open_indices(stack, limit):
    from app.config import EmbeddingSettings, RetrievalSettings
    from app.embeddings import LocalEncoder
    from app.hybrid_retrieval import HybridIndex
    encoder = LocalEncoder(EmbeddingSettings(ROOT / f"data/models/{E5}"))
    indices = {name: stack.enter_context(HybridIndex(ROOT / f"data/hybrid-{name}.db", encoder,
                                                    RetrievalSettings(limit, 1, 60, 6)))
               for name in ("live", "synthetic")}
    for name, index in indices.items():
        reference = read("data/eval/1/wiki-documents.json" if name == "live" else "eval/fixtures/wiki-documents.json")
        assert index.snapshot.source == reference["source"]
        assert {d.page_id: asdict(d) for d in index.snapshot.documents} == {d["page_id"]: d for d in reference["documents"]}
        assert index.snapshot.settings == {"target": 350, "maximum": 450, "overlap": 50, "input_limit": 512}
        assert index.snapshot.algorithm_version == "markdown-chunking-1"
        assert index.metadata["lexical"]["literal_policy_version"] == 1
    return encoder, indices


def preflight(output):
    attempts = offline()
    environment, environment_diagnostics = runtime()
    from app.reranking import LocalCrossEncoder
    from app.retrieval_evaluation import protocol_input
    scorer = LocalCrossEncoder(ROOT / f"data/models/{CE}")
    rows = []
    with ExitStack() as stack:
        encoder, indices = open_indices(stack, 120)
        for case in inputs():
            question = protocol_input(case)
            index = indices[case["source_set"]]
            candidates = index.search(question, 121)
            assert len(candidates) == len(index.last_branch_union) <= 121
            pairs = scorer.preflight(question, [r.chunk for r in candidates])
            question_tokens = len(scorer.tokenizer(question, add_special_tokens=False)["input_ids"])
            rows.append({"id": case["id"], "question_tokens": question_tokens, "pairs": pairs})
        assert scorer._model is None  # No cross-encoder quality inference.
        # Compatibility/loading check only, after ALL tuning pairs pass.
        scorer._load()
        assert encoder._model is not None and scorer._model is not None
        assert not attempts
        write(output, {"passed": True, "environment": environment,
                       "environment_diagnostics": environment_diagnostics, "cases": rows,
                       "e5_identity": encoder.identity, "reranker_identity": scorer.identity,
                       "maximum_pair_tokens": max(p["tokens"] for r in rows for p in r["pairs"]),
                       "network_attempts": len(attempts), "resources": cg(),
                       "cross_encoder_quality_inference": False})


def worker(arm, repeat, output):
    import resource
    attempts = offline()
    environment, environment_diagnostics = runtime()
    before = cg()
    from app.reranking import LocalCrossEncoder, RerankedIndex
    from app.retrieval_evaluation import protocol_input, evidence_hit, retrieval_diagnostics
    timer = perf_counter()
    scorer = LocalCrossEncoder(ROOT / f"data/models/{CE}") if arm == "reranker" else None
    init_seconds = perf_counter() - timer
    if scorer is None:
        import torch
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
    token_seconds = [0.0]
    if scorer:
        original_pair = scorer.pair

        def timed_pair(*args):
            start = perf_counter()
            value = original_pair(*args)
            token_seconds[0] += perf_counter() - start
            return value

        scorer.pair = timed_pair
    rows = []
    e5_load_seconds = []
    with ExitStack() as stack:
        timer = perf_counter()
        encoder, bases = open_indices(stack, 10 if arm == "legacy" else 120)
        index_init_seconds = perf_counter() - timer
        original_load = encoder._load

        def load_e5():
            unloaded = encoder._model is None
            start = perf_counter()
            model = original_load()
            if unloaded:
                e5_load_seconds.append(perf_counter() - start)
            return model

        encoder._load = load_e5
        indices = {name: RerankedIndex(base, scorer) if scorer else base for name, base in bases.items()}
        timings = {}
        for name, base in bases.items():
            for branch in ("_semantic", "_lexical"):
                obj = getattr(base, branch)
                original_search = obj.search

                def measured(*args, _fn=original_search, _key=(name, branch), **kwargs):
                    start = perf_counter()
                    result = _fn(*args, **kwargs)
                    timings[_key] = perf_counter() - start
                    return result

                obj.search = measured
        for pass_name in ("first", "warm"):
            for case in inputs():
                name = case["source_set"]
                index, base = indices[name], bases[name]
                question = protocol_input(case)
                token_seconds[0] = 0.0
                start = perf_counter()
                results = index.search(question, 6 if scorer else 121)
                seconds = perf_counter() - start
                measured_token_seconds = token_seconds[0]
                all_candidates = index.last_candidates if scorer else [r.to_dict() for r in results]
                final = results[:6]
                union = sorted(c.chunk_id for c in base.last_branch_union)
                assert len(union) == len(set(union)) == len(all_candidates) <= (11 if arm == "legacy" else 121)
                pairs = scorer.preflight(question, base.last_branch_union) if scorer else [
                    {"chunk_id": c.chunk_id, "input_sha256": hashlib.sha256(json.dumps(
                        [question, c.search_text], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}
                    for c in sorted(base.last_branch_union, key=lambda c: c.chunk_id)]
                rows.append({"pass": pass_name, "id": case["id"], "source_set": name,
                             "follow_up": "follow_up" in case["tags"], "answerable": case["answerable"],
                             "split": "tuning", "union": union, "inputs": pairs,
                             "candidates": all_candidates, "final": [r.to_dict() for r in final],
                             "hit": evidence_hit(case, final, index.snapshot.source) if case["answerable"] else None,
                             "diagnostics": retrieval_diagnostics(case, index.chunks, base.last_branch_union,
                                                                  final, index.snapshot.source) if case["answerable"] else None,
                             "seconds": seconds, "semantic_seconds": timings[(name, "_semantic")],
                             "lexical_seconds": timings[(name, "_lexical")],
                             "tokenization_seconds": measured_token_seconds if scorer else None,
                             "rerank_seconds": index.last_rerank_seconds if scorer else None})
        assert not attempts
        report = {"arm": arm, "repeat": repeat, "environment": environment,
                  "environment_diagnostics": environment_diagnostics, "rows": rows,
                  "settings": asdict(next(iter(bases.values())).settings),
                  "identities": {name: base.metadata for name, base in bases.items()},
                  "reranker_identity": scorer.identity if scorer else None,
                  "e5_identity": encoder.identity, "e5_load_seconds": e5_load_seconds,
                  "reranker_init_seconds": init_seconds if scorer else None,
                  "index_init_seconds": index_init_seconds,
                  "reranker_load_seconds": scorer.model_loading_seconds if scorer else None,
                  "models_resident_together": bool(encoder._model is not None and scorer and scorer._model is not None),
                  "worker_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                  "cpu_user_seconds": resource.getrusage(resource.RUSAGE_SELF).ru_utime,
                  "cpu_system_seconds": resource.getrusage(resource.RUSAGE_SELF).ru_stime,
                  "cgroup_before": before, "cgroup_after": cg(), "network_attempts": len(attempts),
                  "bundle_bytes": read(RECEIPT)["model_bundle_verification"]["bundle_bytes"],
                  "build_metrics": {key: "N/A: reuse read-only snapshot; no rebuild" for key in
                                    ("durations", "build_only_RSS", "build_disk_increments")}}
        write(output, report)


def stable(row):
    return {k: v for k, v in row.items() if k not in
            {"pass", "seconds", "semantic_seconds", "lexical_seconds", "rerank_seconds", "tokenization_seconds"}}


def exact(left, right):
    # Preserve serialized floating point distinctions, including -0.0 versus 0.0.
    options = {"sort_keys": True, "allow_nan": False, "separators": (",", ":")}
    return json.dumps(left, **options) == json.dumps(right, **options)


def inspect_report(report):
    assert report["network_attempts"] == 0
    if report["arm"] == "reranker":
        assert report["models_resident_together"]
    after = report["cgroup_after"]
    assert int(after["memory.peak"]) <= 5 * 1024**3
    assert int(after["memory.swap.current"]) == 0
    events = dict(line.split() for line in after["memory.events"].splitlines())
    assert all(int(events[key]) == 0 for key in ("max", "oom", "oom_kill")), events
    for row in report["rows"]:
        assert row["split"] == "tuning"
        for candidate in row["candidates"]:
            assert math.isfinite(candidate["reranker_score"] if report["arm"] == "reranker" else candidate["rrf_score"])
    first = [stable(r) for r in report["rows"] if r["pass"] == "first"]
    warm = [stable(r) for r in report["rows"] if r["pass"] == "warm"]
    assert exact(first, warm), "STOP first/warm ranks/scores/inputs differ"
    singles = [r for r in report["rows"] if r["pass"] == "warm" and r["source_set"] == "live"
               and r["answerable"] and not r["follow_up"]]
    assert len(singles) == 9
    return {"hits": sum(r["hit"] for r in singles), "count": 9,
            "warm_mean_seconds": sum(r["seconds"] for r in singles) / 9}


def summarize(directory, repeat, output):
    directory = Path(directory)
    reports = {arm: read(directory / f"{arm}-{repeat}.json") for arm in ARMS}
    preflight_rows = {r["id"]: r for r in read(directory / "preflight.json")["cases"]}
    metrics = {arm: inspect_report(r) for arm, r in reports.items()}
    failures = []
    transitions = []
    for arm, report in reports.items():
        if repeat == 2:
            previous = read(directory / f"{arm}-1.json")
            assert exact([stable(r) for r in previous["rows"]], [stable(r) for r in report["rows"]]), "STOP fresh-repeat mismatch"
            assert exact(previous["environment"], report["environment"]), "STOP fresh-repeat environment mismatch"
    for label in ("first", "warm"):
        controls = {arm: {r["id"]: r for r in reports[arm]["rows"] if r["pass"] == label}
                    for arm in ARMS}
        for key, row in controls["reranker"].items():
            control = controls["control"][key]
            assert row["inputs"] == preflight_rows[key]["pairs"], "STOP preflight/worker inputs changed"
            assert row["union"] == control["union"]
            assert [(p["chunk_id"], p["input_sha256"]) for p in row["inputs"]] == [
                (p["chunk_id"], p["input_sha256"]) for p in control["inputs"]]
            for arm in ("legacy", "control"):
                other = controls[arm][key]
                transitions.append({"id": key, "pass": label, "against": arm,
                                    "before_hit": other["hit"], "after_hit": row["hit"],
                                    "hit_to_miss": other["hit"] is True and row["hit"] is False,
                                    "follow_up": row["follow_up"], "source_set": row["source_set"],
                                    "before_final": other["final"], "after_final": row["final"],
                                    "before_diagnostics": other["diagnostics"], "after_diagnostics": row["diagnostics"]})
    ratio = metrics["reranker"]["warm_mean_seconds"] / metrics["legacy"]["warm_mean_seconds"]
    if ratio > 2:
        failures.append("warm mean >2x legacy")
    if metrics["reranker"]["hits"] < 8:
        failures.append("tuning Hit@5 <8/9")
    result = {"repeat": repeat, "metrics": metrics, "warm_ratio": ratio, "failures": failures,
              "transitions": transitions, "quality_acceptance": False,
              "status": "STOP negative screening" if failures else "screening checks passed; review remaining evidence",
              "next": "STOP; no lock/frozen/independent execution in this runbook"}
    write(output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "transitions"}, ensure_ascii=False))
    if failures:
        raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pack", "check", "preflight", "worker", "inspect", "summarize"))
    parser.add_argument("--output")
    parser.add_argument("--transport", default="transport.json")
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--repeat", type=int, choices=(1, 2))
    parser.add_argument("--directory")
    args = parser.parse_args()
    if args.command == "pack":
        pack(args.output)
    elif args.command == "check":
        print(json.dumps(check(args.transport)))
    elif args.command == "preflight":
        preflight(args.output)
    elif args.command == "worker":
        assert args.arm and args.repeat
        worker(args.arm, args.repeat, args.output)
    elif args.command == "inspect":
        print(json.dumps(inspect_report(read(args.output))))
    else:
        summarize(args.directory, args.repeat, args.output)


if __name__ == "__main__":
    main()
