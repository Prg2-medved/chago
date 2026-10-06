import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from app.chunk_tokenizer import REVISION
from app.chunking import ChunkingError, protect_paths, write_output
from test_chunking import snapshot


ASSETS = Path(__file__).resolve().parents[2] / "data/tokenizers" / REVISION


def run_cli(input_path, output, assets=ASSETS, extra=()):
    return subprocess.run([sys.executable, "-m", "app.chunking", "--input", str(input_path),
                           "--output", str(output), "--tokenizer-path", str(assets), *extra],
                          capture_output=True, text=True, encoding="utf-8", timeout=30)


@pytest.fixture
def input_path(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot()), encoding="utf-8")
    return path


def test_cli_success_and_determinism(input_path, tmp_path):
    if not ASSETS.is_dir():
        pytest.skip("install local E5 assets")
    output = tmp_path / "output.json"
    first = run_cli(input_path, output)
    assert first.returncode == 0, first.stderr
    data = output.read_bytes()
    assert json.loads(first.stdout)["documents"] == 1
    assert json.loads(data)["tokenizer"]["revision"] == REVISION
    assert run_cli(input_path, output).returncode == 0
    assert output.read_bytes() == data


@pytest.mark.parametrize("error", ["snapshot", "settings", "tokenizer", "write"])
def test_cli_failure_preserves_old_output(input_path, tmp_path, error):
    output = tmp_path / "output.json"
    output.write_bytes(b"previous")
    assets = ASSETS
    extra = ()
    if error == "snapshot":
        input_path.write_text('{"schema_version": false}')
    if error == "settings":
        extra = ("--maximum", "451")
    if error == "tokenizer":
        assets = tmp_path / "absent"
    if error == "write":
        output = tmp_path / "missing" / "output.json"
    original = input_path.read_bytes()
    result = run_cli(input_path, output, assets, extra)
    assert result.returncode == 1 and result.stderr.startswith("chunking: ")
    assert "Русский" not in result.stderr
    assert input_path.read_bytes() == original
    assert (tmp_path / "output.json").read_bytes() == b"previous"


def test_cli_protects_input_and_assets(input_path, tmp_path):
    original = input_path.read_bytes()
    assert run_cli(input_path, input_path).returncode == 1
    assert input_path.read_bytes() == original
    assert run_cli(input_path, ASSETS / "output.json").returncode == 1
    alias = tmp_path / "input-alias.json"
    os.link(input_path, alias)
    assert run_cli(input_path, alias).returncode == 1
    assert input_path.read_bytes() == original


def test_path_symlink_and_asset_hardlink(input_path, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    asset = assets / "tokenizer.json"
    asset.write_bytes(b"asset")
    alias = tmp_path / "asset-alias.json"
    os.link(asset, alias)
    with pytest.raises(ChunkingError, match="output_path"):
        protect_paths(input_path, alias, assets)
    symlink = tmp_path / "input-symlink.json"
    try:
        symlink.symlink_to(input_path)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ChunkingError, match="output_path"):
        protect_paths(input_path, symlink, assets)


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_atomic_failure_preserves_old_output(tmp_path, failure):
    output = tmp_path / "output.json"
    output.write_bytes(b"old")
    target = "app.chunking.os.replace" if failure == "replace" else "app.chunking.tempfile.NamedTemporaryFile"
    with patch(target, side_effect=OSError("sensitive details")):
        with pytest.raises(ChunkingError, match="^output_write$"):
            write_output(output, b"new")
    assert output.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.tmp"))
