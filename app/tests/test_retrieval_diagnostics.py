from dataclasses import replace

from app.index_storage import parse_output
from app.retrieval import SearchResult
from app.retrieval_evaluation import evidence_hit, retrieval_diagnostics, source_cover
from test_index_storage import output


def example():
    snapshot = parse_output(output("abcdef"))
    base = snapshot.chunks[0]
    chunks = tuple(replace(base, chunk_id=str(i) * 64, source_ranges=((i, i + 1),),
                           segments=({"kind": "source", "start": i, "end": i + 1, "role": "text"},))
                   for i in range(6))
    case = {"evidence": [{"page_id": base.document.page_id, "locale": base.document.locale,
                           "path": base.document.path, "content_sha256": base.document.content_sha256,
                           "spans": [{"start": 0, "end": 6}]}]}
    return snapshot.source, chunks, case


def test_exact_six_and_scorer_cutoff():
    source, chunks, case = example()
    cover = source_cover(case, chunks, source)
    assert cover["minimum"] == cover["lower_bound"] == cover["upper_bound"] == 6
    assert len(cover["witness"]) == 6
    results = tuple(SearchResult(i + 1, 1, chunk) for i, chunk in enumerate(chunks))
    assert not evidence_hit(case, results, source)
    report = retrieval_diagnostics(case, chunks, chunks, results, source)
    assert report["ranking_loss"] and not report["candidate_loss"]


def test_missing_namespace_generated_and_identity():
    source, chunks, case = example()
    assert source_cover(case, chunks[:-1], source)["missing_ranges"] == [
        {"page_id": chunks[0].document.page_id, "start": 5, "end": 6}]
    assert source_cover(case, chunks, "https://elsewhere.example")["status"] == "impossible"
    generated = tuple(replace(chunk, segments=({"kind": "generated", "text": "abcdef"},)) for chunk in chunks)
    assert not source_cover(case, generated, source)["covered"]
    altered = tuple(replace(chunk, document=replace(chunk.document, content_sha256="f" * 64)) for chunk in chunks)
    assert not source_cover(case, altered, source)["covered"]


def test_overlap_exact_and_unknown_bounds():
    source, chunks, case = example()
    def ranged(chunk, left, right):
        return replace(chunk, source_ranges=((left, right),),
                       segments=({"kind": "source", "start": left, "end": right, "role": "text"},))
    overlapping = (ranged(chunks[0], 0, 4), ranged(chunks[1], 2, 6))
    assert source_cover(case, overlapping, source)["minimum"] == 2
    unknown = source_cover(case, overlapping, source, max_states=0)
    assert unknown["status"] == "unknown" and unknown["minimum"] is None
    assert unknown["lower_bound"] <= 2 <= unknown["upper_bound"]
    results = (SearchResult(1, 1, overlapping[0]),)
    report = retrieval_diagnostics(case, overlapping, overlapping, results, source)
    assert report["inventory"]["minimum"] == 2 and report["ranking_loss"]
    assert retrieval_diagnostics(case, overlapping, overlapping[:1], results, source)["candidate_loss"]
