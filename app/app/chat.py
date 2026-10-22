"""Stateless chat orchestration and cancellation-safe ownership of one LLM slot."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import logging
from time import monotonic
from typing import Protocol

from app.config import load_chat_settings
from app.embeddings import EmbeddingError
from app.grounding import (REFUSAL, Evidence, GroundedAnswer, QuestionBudgetError,
                           build_manifest, pack_context, validate_answer)
from app.hybrid_retrieval import HybridResult
from app.llm_client import LLMClient, LLMError


logger = logging.getLogger(__name__)


class ChatError(ValueError):
    def __init__(self, category: str, status: int) -> None:
        super().__init__(category)
        self.category = category
        self.status = status


class Retrieval(Protocol):
    async def search(self, question: str) -> tuple[HybridResult, ...]: ...


class GenerationGate:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(1)
        self._unavailable = asyncio.Event()
        self.generation_uncertain = False
        self.closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
        self._tasks: set[asyncio.Task[GroundedAnswer]] = set()

    async def _acquire(self) -> None:
        if self._unavailable.is_set():
            raise ChatError("generation_uncertain" if self.generation_uncertain else "chat_closed", 503)
        waiting = asyncio.create_task(self._semaphore.acquire())
        unavailable = asyncio.create_task(self._unavailable.wait())
        transferred = False
        try:
            await asyncio.wait((waiting, unavailable), return_when=asyncio.FIRST_COMPLETED)
            if self._unavailable.is_set():
                raise ChatError("generation_uncertain" if self.generation_uncertain else "chat_closed", 503)
            transferred = True
        finally:
            unavailable.cancel()
            if not transferred:
                if waiting.done() and not waiting.cancelled() and waiting.result():
                    self._semaphore.release()
                else:
                    waiting.cancel()
            # No await after transferring ownership: cancellation at a cleanup
            # suspension point must not strand a successfully acquired slot.
            for task in (waiting, unavailable):
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    async def run(self, operation: Callable[[], GroundedAnswer], timings: dict[str, float]) -> GroundedAnswer:
        started = monotonic()
        try:
            await self._acquire()
        finally:
            timings["wait_ms"] = (monotonic() - started) * 1000
        # Ownership moves to this shielded task before another suspension point.
        task = asyncio.create_task(self._execute(operation))
        self._tasks.add(task)
        def finished(done: asyncio.Task[GroundedAnswer]) -> None:
            self._tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Consume late errors after client cancellation.
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _execute(self, operation: Callable[[], GroundedAnswer]) -> GroundedAnswer:
        try:
            future = asyncio.get_running_loop().run_in_executor(self._executor, operation)
            future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            return await asyncio.shield(future)
        except LLMError as error:
            if error.generation_uncertain:
                self.generation_uncertain = True
                self._unavailable.set()
                logger.warning("chat outcome=generation_uncertain recovery=operator_required")
            raise
        except asyncio.CancelledError:
            # Lifespan/event-loop shutdown cannot prove remote completion either.
            self.generation_uncertain = True
            self._unavailable.set()
            raise
        finally:
            if not self.generation_uncertain:
                self._semaphore.release()

    async def close(self, grace_seconds: float = 1.0) -> None:
        self.closed = True
        self._unavailable.set()
        if self._tasks:
            await asyncio.wait(tuple(self._tasks), timeout=grace_seconds)
        # Do not cancel an active transport or claim its server generation ended.
        self._executor.shutdown(wait=False, cancel_futures=True)


class ChatService:
    def __init__(self, retrieval: Retrieval) -> None:
        self.retrieval = retrieval
        self.gate = GenerationGate()

    def _generate(self, question: str, manifest: tuple[Evidence, ...], timings: dict[str, float]) -> GroundedAnswer:
        if self.gate.closed:
            raise ChatError("chat_closed", 503)
        client = LLMClient(load_chat_settings())
        packed = pack_context(question, manifest, client)
        if not packed.manifest:
            return GroundedAnswer(REFUSAL, True, ())
        if self.gate.closed:
            raise ChatError("chat_closed", 503)
        started = monotonic()
        try:
            completion = client.complete(packed.messages)
        finally:
            timings["generation_ms"] = (monotonic() - started) * 1000
            logger.info("chat generation_ms=%.3f", timings["generation_ms"])
        return validate_answer(completion.content, packed.manifest)

    async def answer(self, question: str) -> GroundedAnswer:
        started = monotonic()
        timings = {"retrieval_ms": 0.0, "wait_ms": 0.0, "generation_ms": 0.0}
        outcome = "ok"
        try:
            if self.gate.generation_uncertain or self.gate.closed:
                raise ChatError("generation_uncertain" if self.gate.generation_uncertain else "chat_closed", 503)
            retrieval_started = monotonic()
            try:
                results = await self.retrieval.search(question)
            finally:
                timings["retrieval_ms"] = (monotonic() - retrieval_started) * 1000
            manifest = build_manifest([result.chunk for result in results])
            return await self.gate.run(lambda: self._generate(question, manifest, timings), timings)
        except ChatError as error:
            outcome = error.category
            raise
        except LLMError as error:
            outcome = error.category
            raise ChatError(error.category, error.status) from None
        except QuestionBudgetError:
            outcome = "llm_input_limit"
            raise ChatError(outcome, 422) from None
        except EmbeddingError as error:
            outcome = "embedding_input_limit" if str(error) == "embedding_budget" else "retrieval_unavailable"
            raise ChatError(outcome, 422 if outcome == "embedding_input_limit" else 503) from None
        except asyncio.CancelledError:
            outcome = "client_cancelled"
            raise
        except Exception:
            outcome = "retrieval_or_configuration_unavailable"
            raise ChatError(outcome, 503) from None
        finally:
            logger.info("chat outcome=%s query_ms=%.3f retrieval_ms=%.3f wait_ms=%.3f generation_ms=%.3f",
                        outcome, (monotonic() - started) * 1000, timings["retrieval_ms"],
                        timings["wait_ms"], timings["generation_ms"])

    async def close(self) -> None:
        await self.gate.close()
