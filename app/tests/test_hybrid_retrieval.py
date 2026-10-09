from dataclasses import replace
import os
import sqlite3

import numpy as np
import pytest

from app.config import RetrievalSettings
from app.embeddings import EmbeddingError
from app.hybrid_retrieval import HybridIndex, HybridRetrievalError, fuse
from app.lexical_retrieval import LexicalResult
from app.lexical_storage import LexicalStorageError, build
from app.retrieval import RetrievalError, SearchResult
from app.semantic_storage import SemanticStorageError, write_semantic
from test_retrieval import retrieval_inputs
from test_semantic_storage import metadata, semantic_snapshot, unit_matrix


@pytest.fixture
def hybrid_inputs(retrieval_inputs):
    source, encoder, calls = retrieval_inputs
    path = source.with_name("hybrid.db")
    build(source, path)
    return path, encoder, calls


def test_real_branches_and_provenance(hybrid_inputs):
    path, encoder, calls = hybrid_inputs
    before = path.read_bytes()
    with HybridIndex(path, encoder) as index:
        results = index.search("Русский", 100)
        assert len(results) == 3
        assert [r.chunk.chunk_id[0] for r in results] == ["a", "b", "c"]
        assert results[0].score == 2 / 61
        assert results[0].cosine_score == 1
        assert results[0].bm25_score < 0
        assert results[0].to_dict()["segments"][0]["kind"] == "generated"
        assert "markdown" not in results[0].to_dict()
        assert index.search("Русский", 100) == results
        assert index._semantic.snapshot is index._lexical.snapshot
    assert calls == ["Русский", "Русский"]
    assert path.read_bytes() == before
    with pytest.raises(HybridRetrievalError, match="hybrid_closed"):
        index.search("x")


def test_known_rrf_overlap_ties_limits():
    chunk = semantic_snapshot().chunks[0]
    a, b, c, d = [replace(chunk, chunk_id=char * 64) for char in "abcd"]
    semantic = (SearchResult(1, .9, b), SearchResult(2, .8, a), SearchResult(3, .7, c))
    lexical = (LexicalResult(1, -3, d, ()), LexicalResult(2, -2, c, ()), LexicalResult(3, -1, a, ()))
    results = fuse(semantic, lexical, 60, 100)
    assert [r.chunk.chunk_id[0] for r in results] == ["a", "c", "b", "d"]
    assert results[0].score == 1 / 62 + 1 / 63
    assert results[0].semantic_rank == 2 and results[0].lexical_rank == 3
    assert results[2].lexical_rank is None
    assert results[3].cosine_score is None
    assert [r.rank for r in results] == [1, 2, 3, 4]
    assert fuse(semantic, lexical, 60, 1) == results[:1]
    assert len({r.chunk.chunk_id for r in results}) == 4


def test_valid_empty_lexical_and_branch_limits(hybrid_inputs):
    path, encoder, calls = hybrid_inputs
    with HybridIndex(path, encoder, RetrievalSettings(1, 1, 60, 6)) as index:
        results = index.search("unknown", 100)
        assert len(results) == 1
        assert results[0].score == 1 / 61
        assert results[0].lexical_rank is None


def test_empty_inventory_inference_and_errors(hybrid_inputs):
    path, encoder, calls = hybrid_inputs
    source = path.with_name("empty-semantic.db")
    snapshot = replace(semantic_snapshot(), chunks=())
    write_semantic(source, snapshot, unit_matrix(0), metadata())
    build(source, path)
    with HybridIndex(path, encoder) as index:
        assert index.search("valid") == ()
        assert calls == ["valid"]
        for question in ("", " ", None):
            with pytest.raises(EmbeddingError):
                index.search(question)
        for k in (True, 0, -1, 1.2):
            with pytest.raises(HybridRetrievalError):
                index.search("valid", k)
        def overflow(question):
            raise EmbeddingError("embedding_input_limit")
        encoder.encode_query = overflow
        with pytest.raises(EmbeddingError, match="embedding_input_limit"):
            index.search("long")
        def backend(question):
            raise RuntimeError("private backend")
        encoder.encode_query = backend
        with pytest.raises(HybridRetrievalError, match="^hybrid_branch$"):
            index.search("valid")


@pytest.mark.parametrize("failure", ["missing", "vector", "identity", "lexical"])
def test_compatibility_failures(hybrid_inputs, failure):
    path, encoder, calls = hybrid_inputs
    if failure == "identity":
        encoder.identity["revision"] = "other"
    else:
        connection = sqlite3.connect(path)
        try:
            connection.execute({"missing": "DROP TABLE chunk_fts", "vector": "UPDATE chunk_embeddings SET vector=x'00'",
                                "lexical": "UPDATE chunk_fts SET search_text='stale'"}[failure])
            connection.commit()
        finally:
            connection.close()
    with pytest.raises((LexicalStorageError, SemanticStorageError, RetrievalError)):
        HybridIndex(path, encoder)
    assert calls == []
    # A failed constructor has closed all retained SQLite handles.
    path.unlink()


def test_branch_failure_no_fallback(hybrid_inputs, monkeypatch):
    path, encoder, calls = hybrid_inputs
    with HybridIndex(path, encoder) as index:
        def fail(*args):
            raise sqlite3.OperationalError("private backend")
        monkeypatch.setattr(index._lexical, "search", fail)
        with pytest.raises(HybridRetrievalError, match="^hybrid_branch$"):
            index.search("question")


def test_one_generation_during_replacement(hybrid_inputs):
    path, encoder, calls = hybrid_inputs
    replacement = path.with_name("replacement.db")
    source = path.with_name("replacement-semantic.db")
    write_semantic(source, replace(semantic_snapshot(), chunks=()), unit_matrix(0), metadata())
    build(source, replacement)
    with HybridIndex(path, encoder) as index:
        before = index.search("Русский")
        try:
            os.replace(replacement, path)
        except PermissionError:
            assert index.search("Русский") == before
        else:
            assert index.search("Русский") == before
    if replacement.exists():
        os.replace(replacement, path)
    with HybridIndex(path, encoder) as index:
        assert index.search("Русский") == ()


def test_invalid_settings_before_inference(hybrid_inputs):
    path, encoder, calls = hybrid_inputs
    with pytest.raises(HybridRetrievalError):
        HybridIndex(path, encoder, settings=False)
    assert calls == []
