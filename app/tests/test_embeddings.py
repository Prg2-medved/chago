from dataclasses import replace
import hashlib
from pathlib import Path
import socket

import numpy as np
import pytest

from app.chunk_tokenizer import ASSET_HASHES, REVISION, passage
from app.config import EmbeddingSettings
from app.embeddings import EmbeddingError, LocalEncoder, manifest, normalized_vectors, verify_assets
from app.index_storage import StoredChunk
from app.ingestion import Document


def test_manifest_tokenizer_contract():
    expected = manifest()
    assert expected["revision"] == REVISION
    assert len(expected["assets_sha256"]) == 8
    assert {name: expected["assets_sha256"][name] for name in ASSET_HASHES} == ASSET_HASHES


@pytest.fixture
def miniature_assets(tmp_path, monkeypatch):
    expected = manifest()
    hashes = {}
    for name in expected["assets_sha256"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
        hashes[name] = hashlib.sha256(name.encode()).hexdigest()
    monkeypatch.setattr("app.embeddings.manifest", lambda: {**expected, "assets_sha256": hashes})
    return EmbeddingSettings(tmp_path)


@pytest.mark.parametrize("name", list(manifest()["assets_sha256"]))
@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_corrupt_no_pickle_fallback(miniature_assets, name, corrupt):
    path = miniature_assets.model_path
    (path / "pytorch_model.bin").write_bytes(b"not a fallback")
    target = path / name
    if corrupt:
        target.write_bytes(b"corrupt")
    else:
        target.unlink()
    with pytest.raises(EmbeddingError, match="embedding_assets"):
        verify_assets(miniature_assets)


def test_identity(miniature_assets):
    with pytest.raises(EmbeddingError, match="embedding_identity"):
        verify_assets(replace(miniature_assets, revision="other"))


@pytest.mark.parametrize("value", [0, float("nan"), float("inf")])
def test_invalid_vectors(value):
    with pytest.raises(EmbeddingError, match="embedding_vectors"):
        normalized_vectors(np.full((1, 384), value), 1)


def test_normalized_float32():
    vectors = normalized_vectors(np.ones((2, 384)), 2)
    assert vectors.dtype == np.dtype("<f4")
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)


@pytest.fixture
def fake_encoder():
    encoder = object.__new__(LocalEncoder)
    encoder.settings = EmbeddingSettings(Path("unused"), batch_size=2)
    class Tokenizer:
        def count(self, text, special=False):
            return 513 if text.endswith("overflow") else 512
        def ids(self, text):
            return [0, 7, 2]
    class Backend:
        def __init__(self):
            self.calls = []
            self.tokenizer = lambda *args, **kwargs: {"input_ids": [0, 7, 2]}
        def encode(self, texts, **kwargs):
            self.calls.append((texts, kwargs))
            values = np.zeros((len(texts), 384))
            for i in range(len(texts)):
                values[i, i] = 2
            return values
    encoder.tokenizer = Tokenizer()
    encoder._model = Backend()
    return encoder


def test_prefix_boundary_batch_mapping(fake_encoder):
    query = fake_encoder.encode_query("question")
    assert query[0] == 1
    calls = fake_encoder._model.calls
    assert calls[0][0] == ["query: question"]
    assert calls[0][1]["prompt"] == ""
    assert calls[0][1]["batch_size"] == 2
    vectors = fake_encoder._encode(["passage: first", "passage: second"])
    assert vectors[0, 0] == vectors[1, 1] == 1
    with pytest.raises(EmbeddingError, match="embedding_budget"):
        fake_encoder.encode_query("overflow")
    assert len(calls) == 2


@pytest.mark.parametrize("question", ["", " \n\t", None, 1])
def test_invalid_question(fake_encoder, question):
    with pytest.raises(EmbeddingError, match="embedding_query"):
        fake_encoder.encode_query(question)
    assert fake_encoder._model.calls == []


def test_real_minimal_offline_assets(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    path = root / "data" / "models" / REVISION
    if not path.is_dir():
        pytest.skip("preinstalled real eight-file E5 assets unavailable")
    def forbidden(*args, **kwargs):
        pytest.fail("runtime network access")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    encoder = LocalEncoder(EmbeddingSettings(path))
    assert encoder._model is None
    query = encoder.encode_query("Как настроить доступ к Wiki.js?")
    assert query.shape == (384,)
    np.testing.assert_allclose(np.linalg.norm(query), 1, atol=1e-5)
    assert encoder._model.tokenizer.is_fast
    # Every actual inference input checks backend IDs against LocalE5.
    np.testing.assert_array_equal(query, encoder.encode_query("Как настроить доступ к Wiki.js?"))
    assert not (path / "pytorch_model.bin").exists()
    assert not (path / "sentencepiece.bpe.model").exists()
    for limit in (512, 513):
        candidate = next("x " * count for count in range(490, 520)
                         if encoder.tokenizer.count("query: " + "x " * count, special=True) == limit)
        if limit == 512:
            assert encoder.encode_query(candidate).shape == (384,)
        else:
            with pytest.raises(EmbeddingError, match="embedding_budget"):
                encoder.encode_query(candidate)
    chunks = []
    for i, text in enumerate(("Настройка доступа к Wiki.js.", "```sh\ncmd --full\n```", "| a | б |\n|---|---|\n| 1 | 2 |\n"), 1):
        doc = Document(i, "ru", f"test-{i}", "Тест", f"https://wiki.example/ru/test-{i}",
                       "2026-10-09T00:00:00Z", text, hashlib.sha256(text.encode()).hexdigest())
        chunks.append(StoredChunk(
            str(i) * 64, "https://wiki.example", doc, ("Раздел",), 0,
            ({"kind": "source", "role": "text", "start": 0, "end": len(text)},),
            ((0, len(text)),), text, encoder.tokenizer.count(text),
            encoder.tokenizer.count(passage(doc.title, ("Раздел",), text), special=True), {},
        ))
    vectors = encoder.encode_passages(chunks)
    assert vectors.shape == (len(chunks), 384)
    encoder.settings = replace(encoder.settings, batch_size=1)
    np.testing.assert_allclose(vectors, encoder.encode_passages(chunks), atol=1e-5)
    if chunks:
        with pytest.raises(EmbeddingError, match="embedding_token_counts"):
            encoder.encode_passages([replace(chunks[0], input_tokens=1)])
