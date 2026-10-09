import json

import pytest

from app.retrieval import main
from app.index_storage import write_snapshot
from test_retrieval import retrieval_inputs
from test_semantic_storage import semantic_snapshot


@pytest.mark.parametrize("k,expected", [(None, 3), ("1", 1), ("100", 3)])
def test_cli_json(retrieval_inputs, monkeypatch, capsys, k, expected):
    path, encoder, calls = retrieval_inputs
    monkeypatch.setattr("app.retrieval.LocalEncoder", lambda settings: encoder)
    args = ["query", "--index", str(path), "--question", "secret-question"]
    if k is not None:
        args += ["--top-k", k]
    assert main(args) == 0
    results = json.loads(capsys.readouterr().out)
    assert len(results) == expected
    assert results[0]["rank"] == 1
    assert calls == ["secret-question"]


@pytest.mark.parametrize("failure", ["missing", "storage-only", "identity", "k"])
def test_errors_safe(retrieval_inputs, monkeypatch, capsys, failure):
    path, encoder, calls = retrieval_inputs
    monkeypatch.setattr("app.retrieval.LocalEncoder", lambda settings: encoder)
    if failure == "missing":
        path.unlink()
    elif failure == "storage-only":
        write_snapshot(path, semantic_snapshot())
    elif failure == "identity":
        encoder.identity["revision"] = "secret-credential"
    args = ["query", "--index", str(path), "--question", "secret-question"]
    if failure == "k":
        args += ["--top-k", "0"]
    assert main(args) == 1
    stderr = capsys.readouterr().err
    assert "secret-question" not in stderr
    assert "secret-credential" not in stderr
    assert semantic_snapshot().documents[0].markdown not in stderr


def test_evaluate_missing_input_safe(retrieval_inputs, monkeypatch, capsys, tmp_path):
    path, encoder, calls = retrieval_inputs
    monkeypatch.setattr("app.retrieval.LocalEncoder", lambda settings: encoder)
    missing = str(tmp_path / "secret-credential")
    assert main(["evaluate", "--index", str(path), "--questions", missing,
                 "--manifest", missing, "--snapshot", missing]) == 1
    stderr = capsys.readouterr().err
    assert "secret-credential" not in stderr


def test_argument_errors_do_not_echo_values(capsys):
    with pytest.raises(SystemExit) as error:
        main(["query", "--index", "missing.db", "--question", "secret-question",
              "--top-k", "secret-credential"])
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "secret-question" not in stderr
    assert "secret-credential" not in stderr
