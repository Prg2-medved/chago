from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from app.embeddings import EmbeddingError
from app.retrieval import RetrievalError, SemanticIndex
from app.semantic_storage import write_semantic
from test_semantic_storage import metadata, semantic_snapshot


@pytest.fixture
def retrieval_inputs(tmp_path):
    snapshot = semantic_snapshot()
    first = snapshot.chunks[0]
    snapshot = replace(snapshot, chunks=tuple(replace(first, chunk_id=char * 64, ordinal=i)
                                             for i, char in enumerate(("c", "a", "b"))))
    matrix = np.zeros((3, 384), dtype="<f4")
    matrix[0, 0] = matrix[1, 0] = matrix[2, 1] = 1
    path = tmp_path / "semantic.db"
    write_semantic(path, snapshot, matrix, metadata())
    calls = []
    def encode(question):
        if not isinstance(question, str) or not question.strip():
            raise EmbeddingError("embedding_query")
        calls.append(question)
        vector = np.zeros(384, dtype="<f4")
        vector[1 if question == "second" else 0] = 1
        return vector
    encoder = SimpleNamespace(identity={key: value for key, value in metadata().items() if key not in ("format_version", "runtime")}, encode_query=encode)
    return path, encoder, calls


def test_geometry_ties_repeat_no_history(retrieval_inputs):
    path, encoder, calls = retrieval_inputs
    index = SemanticIndex(path, encoder)
    first = index.search("first")
    assert [result.chunk.chunk_id[0] for result in first] == ["a", "c", "b"]
    assert [result.score for result in first] == [1, 1, 0]
    assert [result.rank for result in first] == [1, 2, 3]
    assert index.search("second", 1)[0].chunk.chunk_id[0] == "b"
    assert index.search("first", 100) == first
    assert calls == ["first", "second", "first"]
    assert not index.matrix.flags.writeable


@pytest.mark.parametrize("k", [0, -1, 1.5, True, None, "1"])
def test_invalid_k(retrieval_inputs, k):
    path, encoder, calls = retrieval_inputs
    with pytest.raises(RetrievalError, match="retrieval_k"):
        SemanticIndex(path, encoder).search("question", k)
    assert not calls


def test_invalid_question(retrieval_inputs):
    path, encoder, calls = retrieval_inputs
    with pytest.raises(EmbeddingError):
        SemanticIndex(path, encoder).search(" ")


def test_mismatch_before_query(retrieval_inputs):
    path, encoder, calls = retrieval_inputs
    encoder.identity = {**encoder.identity, "revision": "other"}
    with pytest.raises(RetrievalError, match="retrieval_identity_rebuild"):
        SemanticIndex(path, encoder)
    assert not calls


def test_empty(retrieval_inputs):
    path, encoder, calls = retrieval_inputs
    snapshot = replace(semantic_snapshot(), chunks=())
    write_semantic(path, snapshot, np.empty((0, 384), dtype="<f4"), metadata())
    assert SemanticIndex(path, encoder).search("question") == ()


def test_source_slices_generated_metadata(retrieval_inputs):
    path, encoder, calls = retrieval_inputs
    result = SemanticIndex(path, encoder).search("question", 1)[0]
    payload = result.to_dict()
    chunk = result.chunk
    assert payload["source"] == chunk.source
    assert payload["source_url"] == chunk.document.source_url
    assert payload["structure"] == chunk.structure
    assert payload["heading_path"] == chunk.heading_path
    assert "markdown" not in payload
    sources = "".join(chunk.document.markdown[start:end] for start, end in chunk.source_ranges)
    assert sources == chunk.document.markdown
    assert any(segment["kind"] == "generated" for segment in payload["segments"])
    assert payload["source_ranges"] == chunk.source_ranges
