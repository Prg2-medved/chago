import json
import subprocess
import sys

import pytest

from app.lexical_storage import LexicalStorageError, main, protect_paths
from test_lexical_storage import semantic_file


def test_build_cli(semantic_file):
    target = semantic_file.with_name("lexical.db")
    process = subprocess.run([sys.executable, "-m", "app.lexical_storage", "build", "--input", str(semantic_file),
                              "--output", str(target), "--model-path", str(target.parent / "absent")],
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["chunks"] == 1


@pytest.mark.parametrize("argv", [["build", "--input", "private-input"], ["build", "--secret", "private-input"]])
def test_safe_arguments(argv, capsys):
    with pytest.raises(SystemExit) as error:
        main(argv)
    assert error.value.code == 2
    assert capsys.readouterr().err == "lexical: arguments\n"


def test_safe_missing(tmp_path, capsys):
    assert main(["build", "--input", str(tmp_path / "private"), "--output", str(tmp_path / "output")]) == 1
    assert capsys.readouterr().err == "lexical: lexical_build\n"


def test_alias_protection(semantic_file):
    assets = semantic_file.parent / "assets"
    assets.mkdir()
    alias = semantic_file.with_name("alias.db")
    alias.hardlink_to(semantic_file)
    model = assets / "model"
    model.write_bytes(b"model")
    model_alias = semantic_file.with_name("model-alias.db")
    model_alias.hardlink_to(model)
    for output in (semantic_file, alias, assets / "index.db", model_alias):
        with pytest.raises(LexicalStorageError, match="lexical_path"):
            protect_paths(semantic_file, output, assets)
    with pytest.raises(LexicalStorageError, match="lexical_path"):
        protect_paths(model_alias, semantic_file.with_name("out.db"), assets)


def test_symlink_protection(semantic_file):
    alias = semantic_file.with_name("symlink.db")
    try:
        alias.symlink_to(semantic_file)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(LexicalStorageError, match="lexical_path"):
        protect_paths(semantic_file, alias, semantic_file.parent / "assets")
