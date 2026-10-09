import json

import pytest

from app.hybrid_retrieval import main
from app.lexical_storage import build
from app.semantic_storage import write_semantic
from test_hybrid_retrieval import hybrid_inputs
from test_retrieval import retrieval_inputs
from test_semantic_storage import metadata, semantic_snapshot, unit_matrix


def test_defaults_overrides_json(hybrid_inputs, monkeypatch, capsys):
    path, encoder, calls = hybrid_inputs
    monkeypatch.setattr("app.hybrid_retrieval.LocalEncoder", lambda settings: encoder)
    assert main(["query", "--index", str(path), "--question", "Русский"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output) == 3
    assert output[0]["rrf_score"] == 2 / 61
    assert output[0]["source_ranges"] and output[0]["structure"]
    assert main(["query", "--index", str(path), "--question", "Русский", "--top-k", "1",
                 "--semantic-candidates", "1", "--lexical-candidates", "1", "--rrf-constant", "1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["rrf_score"] == 1


def test_empty_json_and_missing_assets(hybrid_inputs, monkeypatch, capsys):
    path, encoder, calls = hybrid_inputs
    source = path.with_name("empty.db")
    snapshot = semantic_snapshot(empty=True)
    write_semantic(source, snapshot, unit_matrix(0), metadata())
    build(source, path)
    monkeypatch.setattr("app.hybrid_retrieval.LocalEncoder", lambda settings: encoder)
    assert main(["query", "--index", str(path), "--question", "valid"]) == 0
    assert capsys.readouterr().out == "[]\n"
    assert calls == ["valid"]
    from app.embeddings import EmbeddingError
    def missing(settings):
        raise EmbeddingError("embedding_assets")
    monkeypatch.setattr("app.hybrid_retrieval.LocalEncoder", missing)
    assert main(["query", "--index", str(path), "--question", "valid"]) == 1
    assert capsys.readouterr().err == "hybrid: embedding_assets\n"


def test_settings_before_encoder_and_safe_args(hybrid_inputs, monkeypatch, capsys):
    path, encoder, calls = hybrid_inputs
    monkeypatch.setattr("app.hybrid_retrieval.LocalEncoder", lambda settings: pytest.fail("encoder created"))
    assert main(["query", "--index", str(path), "--question", "private-question", "--top-k", "0"]) == 1
    assert capsys.readouterr().err == "hybrid: configuration\n"
    with pytest.raises(SystemExit):
        main(["query", "--index", str(path), "--question", "private-question", "--top-k", "private-value"])
    assert capsys.readouterr().err == "retrieval: arguments\n"


def test_model_path_override(hybrid_inputs, monkeypatch, capsys):
    path, encoder, calls = hybrid_inputs
    settings_seen = []
    def create(settings):
        settings_seen.append(settings)
        return encoder
    monkeypatch.setattr("app.hybrid_retrieval.LocalEncoder", create)
    assert main(["query", "--index", str(path), "--question", "valid", "--model-path", "local-model"]) == 0
    capsys.readouterr()
    assert str(settings_seen[0].model_path) == "local-model"
