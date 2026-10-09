import json
import subprocess
import sqlite3
import sys

import pytest

from app.lexical_retrieval import main
from test_lexical_storage import digest, lexical_file, semantic_file


@pytest.mark.parametrize("question", ['OR NOT NEAR title:Русский * (code)', '"code" "unterminated', "'; DROP TABLE chunks; --"])
def test_literal_safe_query(lexical_file, question, capsys):
    before = digest(lexical_file)
    assert main(["query", "--index", str(lexical_file), "--question", question]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)
    assert digest(lexical_file) == before


def test_safe_errors(lexical_file, capsys):
    assert main(["query", "--index", str(lexical_file), "--question", "sensitive-question", "--top-k", "0"]) == 1
    assert capsys.readouterr().err == "lexical: lexical_k\n"
    with pytest.raises(SystemExit):
        main(["query", "--question", "sensitive-question", "--top-k", "private-value"])
    assert capsys.readouterr().err == "lexical: arguments\n"


def test_subprocess_without_heavy_imports(lexical_file):
    before = digest(lexical_file)
    code = """
import sys
for name in ('numpy', 'torch', 'sentence_transformers', 'transformers', 'tokenizers', 'app.embeddings'):
    sys.modules[name] = None
from app.lexical_retrieval import main
raise SystemExit(main(['query', '--index', sys.argv[1], '--question', 'Русский']))
"""
    result = subprocess.run([sys.executable, "-c", code, str(lexical_file)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["rank"] == 1
    assert digest(lexical_file) == before


def test_module_invocation(lexical_file):
    result = subprocess.run([sys.executable, "-m", "app.lexical_retrieval", "query", "--index", str(lexical_file),
                             "--question", "Русский"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert "markdown" not in report[0]
    assert report[0]["source_ranges"]
    assert "bm25_score" in report[0]


def test_backend_initialization_error_safe(lexical_file, monkeypatch, capsys):
    def fail(*args):
        raise sqlite3.OperationalError("private backend and question")
    monkeypatch.setattr("app.lexical_retrieval.LexicalIndex._initialize", fail)
    assert main(["query", "--index", str(lexical_file), "--question", "private-question"]) == 1
    assert capsys.readouterr().err == "lexical: lexical_query\n"
    lexical_file.unlink()
