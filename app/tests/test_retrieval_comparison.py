from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
import subprocess
import sys

import pytest

from app.config import RetrievalSettings
from app.evaluation import ValidationError
from app.lexical_storage import build
from app.retrieval import SearchResult
from app.retrieval_comparison import merge_reports, stable_results
from app.retrieval_evaluation import evaluate, evidence_hit
from app.semantic_storage import write_semantic
from test_retrieval_evaluation import evaluation_inputs, fake_index
from test_semantic_storage import unit_matrix


def comparison_reports(inputs, split="all"):
    package, live, synthetic = inputs
    reports = {}
    for mode in ("semantic", "lexical", "hybrid"):
        report = evaluate(*package.paths[:3], live, package.paths[3], synthetic, split=split,
                          runtime_metadata={"live": {"inference": mode != "lexical"}, "synthetic": {"inference": mode != "lexical"}})
        report.update(mode=mode, requested_split=split, effective_settings=asdict(RetrievalSettings()),
                      embedding_settings={"batch_size": 16, "cpu_threads": 4}, policy_versions={"query": 1, "literal": 1})
        reports[mode] = report
    return reports


def test_three_modes_splits_aggregates_and_frozen_inputs(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    before = [path.read_bytes() for path in package.paths]
    reports = comparison_reports(evaluation_inputs)
    combined = merge_reports(reports)
    assert combined["report_schema_version"] == 1
    assert combined["live_single_question"]["hybrid"]["count"] == 3
    assert combined["modes"]["hybrid"]["groups"]["synthetic"]["holdout"]["single_question"]["hit_at_5"] is None
    assert combined["modes"]["hybrid"]["groups"]["live"]["tuning"]["follow_up"]["count"] == 1
    assert "already measured" in combined["holdout_exposure"]
    assert before == [path.read_bytes() for path in package.paths]
    assert all(report["fingerprints"] == reports["semantic"]["fingerprints"] for report in reports.values())
    tuning = merge_reports(comparison_reports(evaluation_inputs, "tuning"))
    assert all(case["split"] == "tuning" for report in tuning["modes"].values() for case in report["cases"])
    assert not tuning["quality_acceptance"]["accepted"]


@pytest.mark.parametrize("key", ["fingerprints", "reference_fingerprints", "effective_settings", "embedding_settings", "environment", "requested_split"])
def test_merge_rejects_mismatch(evaluation_inputs, key):
    reports = comparison_reports(evaluation_inputs)
    reports["lexical"][key] = {"incompatible": True}
    with pytest.raises(ValidationError, match="incompatible reports"):
        merge_reports(reports)


def test_filter_before_search_and_k_five(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    requested = []
    def search(question, k):
        requested.append((question, k))
        return ()
    live.search = synthetic.search = search
    evaluate(*package.paths[:3], live, package.paths[3], synthetic, split="holdout")
    assert len(requested) == sum(case["split"] == "holdout" for case in package.corpus["questions"])
    assert {k for _, k in requested} == {5}


def test_sixth_chunk_excluded_and_fifth_satisfies(evaluation_inputs):
    assert RetrievalSettings().top_k == 6
    package, live, synthetic = evaluation_inputs
    case = package.corpus["questions"][3]
    good = live.chunks[0]
    dummy = replace(good, source_ranges=())
    six = tuple(SearchResult(i, 1, dummy if i < 6 else good) for i in range(1, 7))
    assert not evidence_hit(case, six, live.snapshot.source)
    five = (*six[:4], SearchResult(5, 1, good), six[4])
    assert evidence_hit(case, five, live.snapshot.source)
    composite = package.corpus["questions"][0]
    first_page = SearchResult(1, 1, good)
    other_page = SearchResult(6, 1, live.chunks[1])
    assert not evidence_hit(composite, (first_page, *six[:4], other_page), live.snapshot.source)
    assert evidence_hit(composite, (first_page, *six[:3], replace(other_page, rank=5), six[4]), live.snapshot.source)
    # An adapter that ignores k still cannot put sixth evidence into Hit@5.
    requested = []
    def overlong(question, k):
        requested.append(k)
        return six
    live.search = overlong
    report = evaluate(*package.paths[:3], live, package.paths[3], synthetic)
    assert "partial" in report["groups"]["live"]["tuning"]["single_question"]["miss_ids"]
    assert set(requested) == {5}


def test_transitions_and_stability(evaluation_inputs):
    reports = comparison_reports(evaluation_inputs)
    first = next(case for case in reports["hybrid"]["cases"] if case["answerable"])
    first["hit"] = False
    combined = merge_reports(reports)
    assert first["id"] in combined["transitions"]["hybrid"]["semantic_hit_to_miss"]
    changed = deepcopy(reports["semantic"])
    for case in changed["cases"]:
        case["duration_seconds"] *= 5
    assert stable_results(changed) == stable_results(reports["semantic"])


@pytest.fixture
def comparison_files(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    indices = {}
    for name, index in (("live", live), ("synthetic", synthetic)):
        semantic = package.root / f"{name}-semantic.db"
        lexical = package.root / f"{name}-hybrid.db"
        write_semantic(semantic, index.snapshot, unit_matrix(len(index.chunks)), index.metadata)
        build(semantic, lexical)
        indices[name] = lexical
    return package, indices


def test_isolated_lexical_worker_no_embedding_imports(comparison_files):
    package, indices = comparison_files
    argv = [part for name, path in zip(("questions", "manifest", "snapshot", "fixtures"), package.paths)
            for part in ("--" + name, str(path))]
    argv += ["--index", str(indices["live"]), "--synthetic-index", str(indices["synthetic"]), "--mode", "lexical"]
    code = """
import sys
for name in ('numpy', 'torch', 'sentence_transformers', 'transformers', 'tokenizers', 'app.embeddings'):
    sys.modules[name] = None
from app.retrieval_comparison import main
raise SystemExit(main(['worker', *sys.argv[1:]]))
"""
    process = subprocess.run([sys.executable, "-c", code, *argv], capture_output=True, encoding="utf-8",
                             env={**os.environ, "PYTHONUTF8": "1"}, timeout=30)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["heavy_imports_loaded"] == []
    assert report["measurement"]["repeated_rankings_equal"]
    assert report["peak_memory_bytes"] > 0
    assert report["cases"][0]["cold"]
    assert all(case["warm_duration_seconds"] >= 0 for case in report["cases"])
