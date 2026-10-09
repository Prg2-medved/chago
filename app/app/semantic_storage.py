"""Additive semantic format v1 with full base validation and atomic publication."""

import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import TYPE_CHECKING, Any

from app.chunk_tokenizer import ASSET_HASHES, MODEL_ID, REVISION
from app.embeddings import DIMENSION, EmbeddingError, LocalEncoder, manifest
from app.index_storage import StorageError, StorageReader, StorageSnapshot, _json, _write_base_snapshot

if TYPE_CHECKING:
    import numpy as np
    from numpy import float32
    from numpy.typing import NDArray


_SCHEMA = """
CREATE TABLE embedding_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), metadata TEXT NOT NULL
);
CREATE TABLE chunk_embeddings (
    chunk_id TEXT PRIMARY KEY NOT NULL REFERENCES chunks(chunk_id), vector BLOB NOT NULL
);
"""


class SemanticStorageError(ValueError):
    """Safe storage error category."""


def expected_identity() -> dict[str, Any]:
    assets = manifest()["assets_sha256"]
    return {
        "model_id": MODEL_ID, "revision": REVISION,
        "assets_fingerprint": hashlib.sha256(_json(assets).encode()).hexdigest(),
        "tokenizer_fingerprint": hashlib.sha256(_json(ASSET_HASHES).encode()).hexdigest(),
        "dimension": DIMENSION, "dtype": "<f4", "normalized": True,
        "input_format_version": 1,
    }


def _check_extension(connection: sqlite3.Connection) -> None:
    reference = sqlite3.connect(":memory:")
    try:
        reference.executescript(_SCHEMA)
        for table in ("embedding_metadata", "chunk_embeddings"):
            for pragma in ("table_info", "foreign_key_list"):
                if connection.execute(f"PRAGMA {pragma}({table})").fetchall() != reference.execute(f"PRAGMA {pragma}({table})").fetchall():
                    raise SemanticStorageError("semantic_schema")
            def keys(database: sqlite3.Connection) -> set[tuple[str, ...]]:
                result = set()
                for row in database.execute(f"PRAGMA index_list({table})"):
                    if row[2]:
                        name = row[1].replace('"', '""')
                        result.add(tuple(item[2] for item in database.execute(f'PRAGMA index_info("{name}")')))
                return result
            if keys(connection) != keys(reference):
                raise SemanticStorageError("semantic_schema")
    finally:
        reference.close()


class SemanticReader:
    def __init__(self, path: Path) -> None:
        # Base checks run first and keep their original error categories.
        base = StorageReader(path)
        self.snapshot = base.snapshot
        try:
            # Read the extension through the same file handle validated by base.
            connection = base._connection
            assert connection is not None
            connection.row_factory = None
            _check_extension(connection)
            rows = connection.execute("SELECT singleton, metadata FROM embedding_metadata").fetchall()
            if len(rows) != 1 or rows[0][0] != 1:
                raise SemanticStorageError("semantic_metadata")
            metadata = json.loads(rows[0][1])
            if not isinstance(metadata, dict) or type(metadata.get("format_version")) is not int or metadata["format_version"] != 1:
                raise SemanticStorageError("semantic_version")
            identity = expected_identity()
            for key, value in identity.items():
                if type(metadata.get(key)) is not type(value) or metadata[key] != value:
                    raise SemanticStorageError("semantic_identity")
            if (self.snapshot.tokenizer.get("model_id") != MODEL_ID
                    or self.snapshot.tokenizer.get("revision") != REVISION
                    or self.snapshot.tokenizer.get("assets_fingerprint") != identity["tokenizer_fingerprint"]):
                raise SemanticStorageError("semantic_identity")
            runtime = metadata.get("runtime")
            if (not isinstance(runtime, dict) or set(runtime) != {"torch", "numpy", "sentence-transformers", "transformers", "tokenizers"}
                    or any(not isinstance(value, str) or not value for value in runtime.values())):
                raise SemanticStorageError("semantic_metadata")
            self.metadata = metadata
            self.chunks = tuple(sorted(self.snapshot.chunks, key=lambda chunk: chunk.chunk_id))
            vectors = dict(connection.execute("SELECT chunk_id, vector FROM chunk_embeddings"))
            if set(vectors) != {chunk.chunk_id for chunk in self.chunks}:
                raise SemanticStorageError("semantic_coverage")
            np = import_module("numpy")
            matrix = np.empty((len(self.chunks), DIMENSION), dtype="<f4")
            for index, chunk in enumerate(self.chunks):
                blob = vectors[chunk.chunk_id]
                if not isinstance(blob, bytes) or len(blob) != DIMENSION * 4:
                    raise SemanticStorageError("semantic_vectors")
                matrix[index] = np.frombuffer(blob, dtype="<f4")
            if (not np.isfinite(matrix).all()
                    or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-5, rtol=0)):
                raise SemanticStorageError("semantic_vectors")
            # Immutable bytes-backed array, including protection against setflags(write=True).
            self.matrix: NDArray[float32] = np.frombuffer(matrix.tobytes(), dtype="<f4").reshape((-1, DIMENSION))
        except (StorageError, SemanticStorageError):
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            raise SemanticStorageError("semantic_read") from None
        finally:
            base.close()


def protect_paths(input_path: Path, output: Path, assets: Path) -> None:
    try:
        if input_path.resolve() == output.resolve() or (output.exists() and input_path.samefile(output)):
            raise SemanticStorageError("semantic_path")
        for path in (input_path, output):
            if path.resolve().is_relative_to(assets.resolve()):
                raise SemanticStorageError("semantic_path")
            if path.exists():
                for asset in assets.rglob("*"):
                    if asset.is_file() and path.samefile(asset):
                        raise SemanticStorageError("semantic_path")
    except OSError:
        raise SemanticStorageError("semantic_path") from None


def write_semantic(output: Path, snapshot: StorageSnapshot, matrix: "NDArray[np.float32]", metadata: dict[str, Any]) -> None:
    temporary: Path | None = None
    try:
        if matrix.shape != (len(snapshot.chunks), DIMENSION):
            raise SemanticStorageError("semantic_vectors")
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=DELETE")
            _write_base_snapshot(connection, snapshot)
            connection.executescript(_SCHEMA)
            with connection:
                connection.execute("INSERT INTO embedding_metadata VALUES (1, ?)", (_json(metadata),))
                connection.executemany("INSERT INTO chunk_embeddings VALUES (?, ?)",
                                       [(chunk.chunk_id, matrix[index].astype("<f4").tobytes())
                                        for index, chunk in enumerate(snapshot.chunks)])
        finally:
            connection.close()
        reader = SemanticReader(temporary)
        if reader.snapshot != snapshot or reader.metadata != metadata:
            raise SemanticStorageError("semantic_integrity")
        os.replace(temporary, output)
    except (sqlite3.Error, OSError, ValueError, TypeError, IndexError):
        raise SemanticStorageError("semantic_write") from None
    finally:
        if temporary is not None:
            for path in (temporary, Path(str(temporary) + "-journal")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def build(input_path: Path, output: Path, encoder: LocalEncoder) -> dict[str, Any]:
    protect_paths(input_path, output, encoder.settings.model_path)
    with StorageReader(input_path) as reader:
        snapshot = reader.snapshot
    if snapshot.tokenizer != encoder.tokenizer.identity:
        raise SemanticStorageError("semantic_identity")
    matrix = encoder.encode_passages(snapshot.chunks)
    metadata = {**encoder.identity, "format_version": 1, "runtime": encoder.runtime()}
    write_semantic(output, snapshot, matrix, metadata)
    return {"documents": len(snapshot.documents), "chunks": len(snapshot.chunks), "identity": metadata}
