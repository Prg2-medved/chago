from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app.evaluation import ValidationError
from app.embeddings import EmbeddingError
from app.index_storage import StoredChunk, StorageSnapshot
from app.ingestion import Document
from app.retrieval import SearchResult
from app.retrieval_evaluation import covers, evaluate, evidence_hit, protocol_input
from test_evaluation import Package
from test_semantic_storage import metadata, semantic_snapshot


def fake_index(reference):
    docs = tuple(Document(**doc) for doc in reference["documents"])
    chunks = tuple(StoredChunk(
        str(i) * 64, reference["source"], doc, (), 0,
        ({"kind": "source", "role": "text", "start": 0, "end": len(doc.markdown)},),
        ((0, len(doc.markdown)),), doc.markdown, 1, 1, {},
    ) for i, doc in enumerate(docs, 1))
    results = tuple(SearchResult(i, 1.0, chunk) for i, chunk in enumerate(chunks, 1))
    calls = []
    def search(question, k):
        calls.append(question)
        return results[:k]
    snap = replace(semantic_snapshot(), source=reference["source"], documents=docs, chunks=chunks)
    return SimpleNamespace(snapshot=snap, chunks=chunks, metadata=metadata(), search=search,
                           encoder=SimpleNamespace(settings=SimpleNamespace(batch_size=16, cpu_threads=4)),
                           calls=calls)


@pytest.fixture
def evaluation_inputs(tmp_path):
    package = Package(tmp_path)
    package.add("synthetic", "Synthetic?", namespace="synthetic")
    package.add("synthetic_follow", "Current?", namespace="synthetic", holdout=True)
    package.corpus["questions"][-1].update(tags=["follow_up"], previous_question="Previous?")
    package.save(synthetic=True)
    return package, fake_index(package.live), fake_index(package.synthetic)


def run(inputs):
    package, live, synthetic = inputs
    return evaluate(*package.paths[:3], live, package.paths[3], synthetic)


def test_protocol_groups_counts_determinism(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    before = [path.read_bytes() for path in package.paths]
    report = run(evaluation_inputs)
    assert report["protocol_version"] == 1
    groups = report["groups"]
    assert groups["live"]["tuning"]["single_question"]["count"] == 2
    assert groups["live"]["holdout"]["single_question"]["count"] == 1
    assert groups["live"]["tuning"]["follow_up"]["count"] == 1
    assert groups["live"]["holdout"]["follow_up"]["count"] == 1
    assert groups["synthetic"]["tuning"]["single_question"]["count"] == 1
    assert groups["synthetic"]["holdout"]["follow_up"]["count"] == 1
    assert groups["synthetic"]["holdout"]["single_question"]["hit_at_5"] is None
    assert synthetic.calls[-1] == "Previous?\nCurrent?"
    assert len(groups["live"]["holdout"]["refuse"]) == 2
    assert len(groups["live"]["tuning"]["clarify"]) == 1
    repeat = run(evaluation_inputs)
    assert report["groups"] == repeat["groups"]
    assert [{key: value for key, value in case.items() if key != "duration_seconds"} for case in report["cases"]] == [
        {key: value for key, value in case.items() if key != "duration_seconds"} for case in repeat["cases"]]
    assert before == [path.read_bytes() for path in package.paths]


@pytest.mark.parametrize("failure", ["document", "source", "settings"])
def test_index_mismatch(evaluation_inputs, failure):
    package, live, synthetic = evaluation_inputs
    if failure == "document":
        live.snapshot = replace(live.snapshot, documents=live.snapshot.documents[:1])
    elif failure == "source":
        live.snapshot = replace(live.snapshot, source=synthetic.snapshot.source)
    else:
        live.snapshot = replace(live.snapshot, settings={**live.snapshot.settings, "target": 100})
    with pytest.raises(ValidationError, match="index:"):
        run(evaluation_inputs)
    assert live.calls == []


def test_followup_overflow_not_shortened(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    def search(question, k):
        if "\n" in question:
            raise EmbeddingError("embedding_budget")
        return ()
    live.search = search
    with pytest.raises(EmbeddingError, match="embedding_budget"):
        run(evaluation_inputs)


def test_composite_partial_conflict_miss(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    live.search = lambda question, k: (SearchResult(1, 1, live.chunks[0]),)
    report = run(evaluation_inputs)
    assert "q0" in report["groups"]["live"]["holdout"]["single_question"]["miss_ids"]
    assert "partial" in report["groups"]["live"]["tuning"]["single_question"]["hit_ids"]


def test_disjoint_union_generated_and_namespaces(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    case = package.corpus["questions"][3]
    chunk = live.chunks[0]
    n = len(chunk.document.markdown)
    middle = n // 2
    first = SearchResult(1, 1, replace(chunk, source_ranges=((0, middle),)))
    second = SearchResult(2, 1, replace(chunk, source_ranges=((middle, n),)))
    assert evidence_hit(case, (first, second), live.snapshot.source)
    gap = replace(second, chunk=replace(chunk, source_ranges=((middle + 1, n),)))
    assert not evidence_hit(case, (first, gap), live.snapshot.source)
    generated = replace(first, chunk=replace(chunk, source_ranges=((0, 1),),
                                            segments=({"kind": "generated", "text": chunk.document.markdown},)))
    assert not evidence_hit(case, (generated,), live.snapshot.source)
    other = SearchResult(1, 1, synthetic.chunks[0])
    assert not evidence_hit(case, (other,), live.snapshot.source)


def test_protocol_never_uses_answers():
    case = {"tags": ["follow_up"], "previous_question": "previous", "question": "current",
            "previous_answer": "secret answer"}
    assert protocol_input(case) == "previous\ncurrent"
    assert covers([(0, 2), (4, 7), (2, 4)], 0, 7)
    assert not covers([(0, 2), (4, 7)], 0, 7)
