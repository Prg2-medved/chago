"""Verified offline CPU E5 encoder. Importing this module does not load a model."""

from collections.abc import Sequence
import argparse
from dataclasses import replace
import hashlib
from importlib import import_module
from importlib.metadata import version
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Never

from app.chunk_tokenizer import LocalE5, MODEL_ID, REVISION, passage
from app.config import EmbeddingSettings, load_embedding_settings
from app.index_storage import StorageError, StoredChunk

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


DIMENSION = 384
INPUT_LIMIT = 512


class EmbeddingError(ValueError):
    """Safe error category without inputs, paths or backend diagnostics."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "semantic: arguments\n")


def manifest() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("embedding_manifest.json").read_text())


def verify_assets(settings: EmbeddingSettings) -> dict[str, Any]:
    expected = manifest()
    if settings.model_id != MODEL_ID or settings.revision != REVISION:
        raise EmbeddingError("embedding_identity")
    try:
        for name, digest in expected["assets_sha256"].items():
            with (settings.model_path / name).open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                    raise EmbeddingError("embedding_assets")
    except OSError:
        raise EmbeddingError("embedding_assets") from None
    return {
        "model_id": MODEL_ID, "revision": REVISION,
        "assets_fingerprint": hashlib.sha256(json.dumps(
            expected["assets_sha256"], sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
        "dimension": DIMENSION, "dtype": "<f4", "normalized": True,
        "input_format_version": 1,
    }


def normalized_vectors(values: object, count: int) -> "NDArray[np.float32]":
    """Validate shape and finite nonzero values before normalizing float32."""
    np = import_module("numpy")
    try:
        vectors = np.asarray(values, dtype="<f4")
        if vectors.shape != (count, DIMENSION) or not np.isfinite(vectors).all():
            raise EmbeddingError("embedding_vectors")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(norms).all() or (norms <= 0).any():
            raise EmbeddingError("embedding_vectors")
        vectors = np.asarray(vectors / norms[:, None], dtype="<f4")
        if (not np.isfinite(vectors).all()
                or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5, rtol=0)):
            raise EmbeddingError("embedding_vectors")
        return vectors
    except (TypeError, ValueError, OverflowError):
        raise EmbeddingError("embedding_vectors") from None


class LocalEncoder:
    def __init__(self, settings: EmbeddingSettings) -> None:
        if settings.batch_size < 1 or settings.cpu_threads < 1:
            raise EmbeddingError("embedding_configuration")
        self.settings = settings
        self.identity = verify_assets(settings)
        try:
            self.tokenizer = LocalE5(settings.model_path, settings.revision)
        except ValueError:
            raise EmbeddingError("embedding_tokenizer") from None
        self.identity["tokenizer_fingerprint"] = self.tokenizer.identity["assets_fingerprint"]
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            # Offline flags are set before importing any Hub/backend code.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            try:
                torch = import_module("torch")
                if torch.version.cuda is not None:
                    raise EmbeddingError("embedding_backend")
                torch.set_num_threads(self.settings.cpu_threads)
                backend = import_module("sentence_transformers")
                model = backend.SentenceTransformer(
                    str(self.settings.model_path.resolve()), device="cpu",
                    local_files_only=True, trust_remote_code=False,
                    model_kwargs={"use_safetensors": True, "local_files_only": True},
                    tokenizer_kwargs={"use_fast": True, "local_files_only": True},
                    prompts={}, default_prompt_name=None,
                )
                if (not model.tokenizer.is_fast or model.get_sentence_embedding_dimension() != DIMENSION
                        or str(model.device) != "cpu"):
                    raise EmbeddingError("embedding_backend")
                model.max_seq_length = INPUT_LIMIT
                self._model = model
            except Exception:
                raise EmbeddingError("embedding_backend") from None
        return self._model

    def _encode(self, inputs: Sequence[str]) -> "NDArray[np.float32]":
        for text in inputs:
            if self.tokenizer.count(text, special=True) > INPUT_LIMIT:
                raise EmbeddingError("embedding_budget")
        if not inputs:
            return import_module("numpy").empty((0, DIMENSION), dtype="<f4")
        model = self._load()
        try:
            # Verify actual backend token IDs for every input, including special tokens.
            for text in inputs:
                expected = self.tokenizer.ids(text)
                actual = model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"]
                if actual != expected:
                    raise EmbeddingError("embedding_tokenizer")
            values = model.encode(
                list(inputs), batch_size=self.settings.batch_size, device="cpu",
                convert_to_numpy=True, normalize_embeddings=False, show_progress_bar=False,
                prompt="", precision="float32",
            )
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingError("embedding_inference") from None
        return normalized_vectors(values, len(inputs))

    def encode_query(self, question: str) -> "NDArray[np.float32]":
        if not isinstance(question, str) or not question.strip():
            raise EmbeddingError("embedding_query")
        return self._encode([f"query: {question}"])[0]

    def encode_passages(self, chunks: Sequence[StoredChunk]) -> "NDArray[np.float32]":
        inputs = [passage(chunk.document.title, chunk.heading_path, chunk.search_text) for chunk in chunks]
        for chunk, text in zip(chunks, inputs):
            if (self.tokenizer.count(text, special=True) != chunk.input_tokens
                    or self.tokenizer.count(chunk.search_text) != chunk.body_tokens):
                raise EmbeddingError("embedding_token_counts")
        return self._encode(inputs)

    def runtime(self) -> dict[str, str]:
        return {name: version(name) for name in ("sentence-transformers", "transformers", "torch", "numpy", "tokenizers")}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ArgumentParser(description="Build an offline CPU semantic snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--input", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--model-path", type=Path)
    args = parser.parse_args(argv)
    # Import canonical module through semantic_storage when invoked with -m.
    from app.semantic_storage import SemanticStorageError, build, protect_paths
    try:
        settings = load_embedding_settings()
        if args.model_path is not None:
            settings = replace(settings, model_path=args.model_path)
        protect_paths(args.input, args.output, settings.model_path)
        report = build(args.input, args.output, LocalEncoder(settings))
    except (EmbeddingError, SemanticStorageError, StorageError) as error:
        print(f"semantic: {error}", file=sys.stderr)
        return 1
    except ValueError:
        print("semantic: embedding_configuration", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
