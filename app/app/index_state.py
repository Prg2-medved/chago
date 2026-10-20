"""One validated active generation, retained until application shutdown."""

import logging
from pathlib import Path

from app.lexical_storage import LexicalReader
from app.reindex_metadata import read_metadata
from app.semantic_storage import SemanticReader


class ActiveIndex:
    def __init__(self, path: Path) -> None:
        self._reader = LexicalReader(path)
        try:
            semantic = SemanticReader._from_base(self._reader)
            self.metadata = read_metadata(self._reader)
            self.snapshot = semantic.snapshot
            self.matrix = semantic.matrix
            self.ordered_ids = tuple(chunk.chunk_id for chunk in semantic.chunks)
            self.semantic_metadata = semantic.metadata
            self.lexical_metadata = self._reader.metadata
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._reader.close()

    def __enter__(self) -> "ActiveIndex":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class IndexState:
    def __init__(self, index: ActiveIndex | None, reason: str | None = None) -> None:
        self.index = index
        self.reason = reason

    @property
    def available(self) -> bool:
        return self.index is not None

    def close(self) -> None:
        if self.index is not None:
            self.index.close()


def load_index_state(path: Path) -> IndexState:
    try:
        if not path.exists():
            reason = "index_missing"
        else:
            return IndexState(ActiveIndex(path))
    except Exception:
        # No backend exception, source text, or path enters the startup log.
        reason = "index_invalid_or_rebuild_required"
    logging.getLogger(__name__).warning("active index unavailable: %s", reason)
    return IndexState(None, reason)
