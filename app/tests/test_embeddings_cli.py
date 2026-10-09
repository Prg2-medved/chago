from dataclasses import replace
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from app.embeddings import EmbeddingError, main
from app.index_storage import write_snapshot
from app.semantic_storage import SemanticReader, SemanticStorageError, build
from test_semantic_storage import metadata, semantic_snapshot, unit_matrix


@pytest.fixture
def build_inputs(tmp_path):
    snapshot = semantic_snapshot()
    first = snapshot.chunks[0]
    snapshot = replace(snapshot, chunks=(first, replace(first, chunk_id="a" * 64, ordinal=1)))
    source = tmp_path / "source.db"
    output = tmp_path / "output.db"
    write_snapshot(source, snapshot)
    encoder = SimpleNamespace(
        settings=SimpleNamespace(model_path=tmp_path / "assets"),
        tokenizer=SimpleNamespace(identity=snapshot.tokenizer),
        identity={key: value for key, value in metadata().items() if key not in ("format_version", "runtime")},
        runtime=lambda: metadata()["runtime"],
        encode_passages=lambda chunks: unit_matrix(len(chunks)),
    )
    return source, output, snapshot, encoder


def test_build_mapping_roundtrip(build_inputs):
    source, output, snapshot, encoder = build_inputs
    before = source.read_bytes()
    report = build(source, output, encoder)
    assert report["chunks"] == 2
    reader = SemanticReader(output)
    assert reader.snapshot == snapshot
    assert reader.chunks[0].chunk_id == "a" * 64
    assert reader.matrix[0, 1] == reader.matrix[1, 0] == 1
    assert source.read_bytes() == before


def test_cli_counts_identity(build_inputs, monkeypatch, capsys):
    source, output, snapshot, encoder = build_inputs
    monkeypatch.setattr("app.embeddings.LocalEncoder", lambda settings: encoder)
    assert main(["build", "--input", str(source), "--output", str(output)]) == 0
    report = capsys.readouterr().out
    assert '"chunks": 2' in report
    assert '"model_id"' in report
    assert snapshot.documents[0].markdown not in report


@pytest.mark.parametrize("failure", ["inference", "write", "integrity", "replace"])
def test_failures_preserve_input_output(build_inputs, monkeypatch, capsys, failure):
    source, output, snapshot, encoder = build_inputs
    build(source, output, encoder)
    before_source, before_output = source.read_bytes(), output.read_bytes()
    def fail(*args, **kwargs):
        if failure == "inference":
            raise EmbeddingError("embedding_inference")
        raise OSError("credential query source must not leak")
    if failure == "inference":
        encoder.encode_passages = fail
    elif failure == "write":
        monkeypatch.setattr("app.semantic_storage._write_base_snapshot", fail)
    elif failure == "integrity":
        monkeypatch.setattr("app.semantic_storage.SemanticReader", fail)
    else:
        monkeypatch.setattr("app.semantic_storage.os.replace", fail)
    monkeypatch.setattr("app.embeddings.LocalEncoder", lambda settings: encoder)
    assert main(["build", "--input", str(source), "--output", str(output)]) == 1
    stderr = capsys.readouterr().err
    assert "credential" not in stderr
    assert "must not leak" not in stderr
    assert source.read_bytes() == before_source
    assert output.read_bytes() == before_output


def test_tokenizer_mismatch(build_inputs):
    source, output, snapshot, encoder = build_inputs
    encoder.tokenizer.identity = {**snapshot.tokenizer, "revision": "other"}
    with pytest.raises(SemanticStorageError, match="semantic_identity"):
        build(source, output, encoder)
    assert not output.exists()


def test_empty_build_no_inference(build_inputs):
    source, output, snapshot, encoder = build_inputs
    empty = replace(snapshot, chunks=())
    write_snapshot(source, empty)
    encoder.encode_passages = lambda chunks: np.empty((0, 384), dtype="<f4")
    assert build(source, output, encoder)["chunks"] == 0
    assert SemanticReader(output).matrix.shape == (0, 384)


def test_argument_errors_safe(capsys):
    with pytest.raises(SystemExit) as error:
        main(["build", "--secret-credential"])
    assert error.value.code == 2
    assert "secret-credential" not in capsys.readouterr().err
