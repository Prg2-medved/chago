import json
import os
import subprocess
import sys

import pytest

from app.index_storage import StorageReader
from test_index_storage import output


def run_cli(input_path, output_path):
    environment = dict(os.environ)
    for name in ("WIKI_TOKEN", "WIKI_DB_PASSWORD", "LLM_BASE_URL"):
        environment.pop(name, None)
    return subprocess.run([sys.executable, "-m", "app.index_storage", "--input", str(input_path),
                           "--output", str(output_path)], capture_output=True, text=True,
                          encoding="utf-8", timeout=30, env=environment)


@pytest.fixture
def input_path(tmp_path):
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(output(), ensure_ascii=False), encoding="utf-8")
    return path


def test_success(input_path, tmp_path):
    path = tmp_path / "storage.db"
    before = input_path.read_bytes()
    for _ in range(2):
        result = run_cli(input_path, path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"documents": 1, "chunks": 1, "storage_version": 1}
        with StorageReader(path) as reader:
            assert len(reader.documents) == len(reader.chunks) == 1
    assert input_path.read_bytes() == before


@pytest.mark.parametrize("alias", ["direct", "hardlink", "symlink"])
def test_input_alias(input_path, tmp_path, alias):
    path = input_path
    if alias != "direct":
        path = tmp_path / "alias.json"
        if alias == "hardlink":
            os.link(input_path, path)
        else:
            try:
                path.symlink_to(input_path)
            except OSError:
                pytest.skip("symlink privilege unavailable")
    before = input_path.read_bytes()
    result = run_cli(input_path, path)
    assert result.returncode == 1
    assert result.stderr.strip() == "storage: output_path"
    assert input_path.read_bytes() == before


@pytest.mark.parametrize("failure", ["json", "validation", "input_missing", "directory_missing", "output_directory"])
def test_failures(input_path, tmp_path, failure):
    path = tmp_path / "storage.db"
    path.write_bytes(b"old")
    if failure == "json":
        input_path.write_text("secret invalid JSON")
    elif failure == "validation":
        input_path.write_text('{"schema_version": false, "secret": "Русский"}', encoding="utf-8")
    elif failure == "input_missing":
        input_path = tmp_path / "missing.json"
    elif failure == "directory_missing":
        path = tmp_path / "absent" / "storage.db"
    elif failure == "output_directory":
        path = tmp_path
    before = input_path.read_bytes() if input_path.exists() else None
    result = run_cli(input_path, path)
    assert result.returncode == 1
    assert result.stderr.startswith("storage: ")
    assert "secret" not in result.stderr and "Русский" not in result.stderr
    assert (tmp_path / "storage.db").read_bytes() == b"old"
    assert (input_path.read_bytes() if input_path.exists() else None) == before
    assert not list(tmp_path.glob("*.tmp*"))
