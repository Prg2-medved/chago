"""One validated active generation, retained until application shutdown."""

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import logging
from pathlib import Path
from typing import TypeVar

from app.config import load_embedding_settings, load_retrieval_settings
from app.embeddings import LocalEncoder
from app.hybrid_retrieval import HybridIndex, HybridResult, HybridRetrievalError
from app.lexical_storage import LexicalReader
from app.reindex_metadata import read_metadata
from app.semantic_storage import SemanticReader

T = TypeVar("T")


async def _wait_owned(future: Future[T]) -> T:
    wrapped = asyncio.wrap_future(future)
    # Consume late failures after cancellation without backend diagnostics.
    wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return await asyncio.shield(wrapped)


class ActiveIndex:
    def __init__(self, path: Path) -> None:
        self._reader = LexicalReader(path)
        try:
            semantic = SemanticReader._from_base(self._reader)
            self._semantic_reader = semantic
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
            self.index = None


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


class RetrievalService:
    """One thread owns SQLite, the lazy encoder, and every search until close."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retrieval")
        self.state = IndexState(None, "index_not_loaded")
        self._hybrid: HybridIndex | None = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._started or self._closed:
            raise HybridRetrievalError("retrieval_lifecycle")
        self._started = True
        await _wait_owned(self._executor.submit(self._load))

    def _load(self) -> None:
        self.state = load_index_state(self._path)

    async def search(self, question: str) -> tuple[HybridResult, ...]:
        if not self._started or self._closed:
            raise HybridRetrievalError("retrieval_lifecycle")
        # Shield the queued operation: cancellation must not interrupt ownership.
        return await _wait_owned(self._executor.submit(self._search, question))

    def _search(self, question: str) -> tuple[HybridResult, ...]:
        if self.state.index is None:
            raise HybridRetrievalError("index_unavailable")
        if self._hybrid is None:
            settings = load_retrieval_settings()
            encoder = LocalEncoder(load_embedding_settings())
            self._hybrid = HybridIndex._from_active(self.state.index, encoder, settings)
        return self._hybrid.search(question)

    def _close(self) -> None:
        try:
            if self._hybrid is not None:
                self._hybrid.close()
                self._hybrid = None
        finally:
            self.state.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # FIFO close follows even a cancelled search/start; no event-loop blocking.
        future = self._executor.submit(self._close)
        self._executor.shutdown(wait=False)
        await _wait_owned(future)
