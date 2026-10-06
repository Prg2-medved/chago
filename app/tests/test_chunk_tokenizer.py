from pathlib import Path
import shutil
import socket

import pytest

from app.chunk_tokenizer import ASSET_HASHES, LocalE5, MODEL_ID, PACKAGE_VERSION, REVISION, passage
from app.chunking import ChunkSettings, ChunkingError, build_output, parse_snapshot

from test_chunking import snapshot


ASSETS = Path(__file__).resolve().parents[2] / "data/tokenizers" / REVISION


@pytest.fixture(scope="module")
def e5():
    if not ASSETS.is_dir():
        pytest.skip("Install verified local E5 assets for real acceptance")
    return LocalE5(ASSETS)


def test_real_identity_and_special_tokens(e5):
    assert e5.identity["model_id"] == MODEL_ID
    assert e5.identity["revision"] == REVISION
    assert e5.identity["assets_sha256"] == ASSET_HASHES
    assert e5.identity["package_version"] == PACKAGE_VERSION
    assert len(e5.identity["assets_fingerprint"]) == 64
    assert e5.count("test", True) == e5.count("test") + 2
    assert e5.count(("test " * 600).rstrip(), True) == 602
    assert passage("Title", (), "body") == "passage: Title\n\nbody"


@pytest.mark.parametrize("revision", ["main", "branch", "v1", "0" * 40])
def test_reject_unverified_revision(revision):
    with pytest.raises(ValueError, match="tokenizer_identity"):
        LocalE5(ASSETS, revision)


def test_missing_assets(tmp_path):
    with pytest.raises(ValueError, match="tokenizer_assets"):
        LocalE5(tmp_path)


def test_loader_never_uses_network(e5, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("runtime network attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    assert LocalE5(ASSETS).count("offline", True) > 2
    with pytest.raises(ValueError, match="tokenizer_assets"):
        LocalE5(tmp_path)


def test_real_metadata_reduces_body_budget(e5):
    payload = snapshot("test " * 1200)
    payload["documents"][0]["title"] = ("test " * 470).rstrip()
    result = build_output(parse_snapshot(payload), e5, ChunkSettings())
    assert len(result["chunks"]) > 10
    assert all(chunk["body_tokens"] < 50 and chunk["input_tokens"] <= 512 for chunk in result["chunks"])


def test_corrupt_assets(tmp_path, e5):
    for name in ASSET_HASHES:
        shutil.copyfile(ASSETS / name, tmp_path / name)
    (tmp_path / "tokenizer_config.json").write_text("{}")
    with pytest.raises(ValueError, match="tokenizer_assets"):
        LocalE5(tmp_path)


def test_real_budget_boundaries(e5):
    assert e5.count(("test " * 450).rstrip()) == 450
    assert e5.count(("test " * 510).rstrip(), True) == 512
    result = build_output(parse_snapshot(snapshot("test " * 2500)), e5, ChunkSettings())
    assert result["tokenizer"] == e5.identity
    for chunk in result["chunks"]:
        assert chunk["body_tokens"] <= 450
        assert chunk["input_tokens"] <= 512
        assert chunk["input_tokens"] == e5.count(passage(chunk["title"], tuple(chunk["heading_path"]), chunk["search_text"]), True)


def test_impossible_metadata(e5):
    payload = snapshot("x")
    payload["documents"][0]["title"] = "test " * 600
    with pytest.raises(ChunkingError, match="budget"):
        build_output(parse_snapshot(payload), e5, ChunkSettings())
