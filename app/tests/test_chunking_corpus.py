"""Read-only acceptance: source coverage is not a retrieval metric."""

from collections import Counter
import hashlib
import json
from pathlib import Path

import pytest

from app.chunk_tokenizer import LocalE5, REVISION, passage
from app.chunking import ChunkSettings, build_output, load_snapshot, output_bytes
from app.evaluation import validate_package


ROOT = Path(__file__).resolve().parents[2]


def union(ranges):
    result = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def test_real_frozen_corpus_preservation():
    assets = ROOT / "data/tokenizers" / REVISION
    live = ROOT / "data/eval/1/wiki-documents.json"
    if not assets.is_dir() or not live.is_file():
        pytest.skip("install E5 assets and frozen live snapshot")
    paths = {"live": live, "synthetic": ROOT / "eval/fixtures/wiki-documents.json"}
    manifest = ROOT / "eval/manifest.json"
    questions_path = ROOT / "eval/questions.yaml"
    checked = [*paths.values(), manifest, questions_path]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in checked}
    validate_package(questions_path, manifest, live, paths["synthetic"])
    tokenizer = LocalE5(assets)
    outputs = {}
    documents = {}
    coverage = {}
    for source_set, path in paths.items():
        snapshot = load_snapshot(path)
        result = build_output(snapshot, tokenizer, ChunkSettings())
        assert output_bytes(result) == output_bytes(build_output(snapshot, tokenizer, ChunkSettings()))
        outputs[source_set] = result
        documents[source_set] = {document.page_id: document for document in snapshot.documents}
        coverage[source_set] = {}
        for document in snapshot.documents:
            chunks = [chunk for chunk in result["chunks"] if chunk["page_id"] == document.page_id]
            ranges = []
            for chunk in chunks:
                assert chunk["source_url"] == document.source_url
                rendered = []
                for segment in chunk["segments"]:
                    if segment["kind"] == "source":
                        start, end = segment["start"], segment["end"]
                        assert 0 <= start < end <= len(document.markdown)
                        ranges.append((start, end))
                        rendered.append(document.markdown[start:end])
                    else:
                        assert segment["reason"] in ("table_header", "fence", "separator")
                        rendered.append(segment["text"])
                assert "".join(rendered) == chunk["search_text"]
                assert tokenizer.count(chunk["search_text"]) == chunk["body_tokens"] <= 450
                assert tokenizer.count(passage(document.title, tuple(chunk["heading_path"]), chunk["search_text"]), True) == chunk["input_tokens"] <= 512
            coverage[source_set][document.page_id] = union(ranges)
            assert union(ranges) == ([[0, len(document.markdown)]] if document.markdown else [])
    counts = Counter()
    for question in json.loads(questions_path.read_text(encoding="utf-8"))["questions"]:
        source_set = question["source_set"]
        counts[(source_set, question["split"])] += 1
        source_regions = []
        for evidence in question["evidence"]:
            document = documents[source_set][evidence["page_id"]]
            for span in evidence["spans"]:
                start, end = span["start"], span["end"]
                assert document.markdown[start:end] == span["exact_text"]
                assert any(low <= start < end <= high for low, high in coverage[source_set][document.page_id])
                source_regions.append(document.markdown[start:end])
        for command in question["exact_commands"]:
            assert any(command in region for region in source_regions)
    assert counts == {("live", "tuning"): 14, ("live", "holdout"): 5, ("synthetic", "holdout"): 1}
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in checked}
