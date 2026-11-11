"""Read-only diagnostics, independent of retrieval and generation workers."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import http.client
import json
import socket
import threading
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

from app.chat import GenerationGate
from app.index_state import IndexState

LLMStatus = Literal["ok", "unavailable", "invalid_response", "timeout", "configuration_error"]


@dataclass(frozen=True)
class IndexSnapshot:
    status: Literal["ok", "missing", "invalid"]
    available: bool
    pages: int | None
    chunks: int | None
    indexed_at: str | None


def index_snapshot(state: IndexState) -> IndexSnapshot:
    if state.index is None:
        return IndexSnapshot("missing" if state.reason == "index_missing" else "invalid",
                             False, None, None, None)
    metadata = state.index.metadata
    return IndexSnapshot("ok", True, metadata.document_count, metadata.chunk_count, metadata.indexed_at)


def chat_status(gate: GenerationGate) -> Literal["available", "generation_uncertain", "closed"]:
    if gate.closed:
        return "closed"
    return "generation_uncertain" if gate.generation_uncertain else "available"


def probe(origin: str) -> LLMStatus:
    try:
        url = urlsplit(origin)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username is not None
                or url.password is not None or url.path not in ("", "/") or url.query or url.fragment
                or any(character.isspace() or ord(character) < 32 for character in origin)
                or "\\" in origin or url.netloc.endswith(":")
                or (url.port is not None and not 1 <= url.port <= 65535)):
            return "configuration_error"
        port = url.port
    except ValueError:
        return "configuration_error"
    connection_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(url.hostname, port, timeout=5)
    deadline = monotonic() + 5
    transport_socket: socket.socket | None = None
    def interrupt() -> None:
        # A peer trickling headers/body must not extend the total socket budget.
        if transport_socket is not None:
            try:
                transport_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    timer = threading.Timer(5, interrupt)
    timer.daemon = True
    timer.start()
    response: http.client.HTTPResponse | None = None
    try:
        connection.connect()
        transport_socket = connection.sock
        if monotonic() >= deadline:
            return "timeout"
        if transport_socket is not None:
            transport_socket.settimeout(deadline - monotonic())
        connection.request("GET", "/health", headers={"Connection": "close"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            return "invalid_response"
        if response.status != 200:
            return "unavailable"
        body = bytearray()
        while not response.isclosed():
            remaining = deadline - monotonic()
            if remaining <= 0:
                return "timeout"
            if transport_socket is not None:
                transport_socket.settimeout(remaining)
            chunk = response.read1(min(4096, 65537 - len(body)))
            body.extend(chunk)
            if len(body) > 65536:
                return "invalid_response"
            if not chunk:
                break
        if response.length not in (None, 0):
            return "timeout" if monotonic() >= deadline else "invalid_response"
        value = json.loads(body)
        return "ok" if isinstance(value, dict) and value.get("status") == "ok" else "invalid_response"
    except (TimeoutError, socket.timeout):
        return "timeout"
    except (ValueError, UnicodeError, RecursionError, http.client.HTTPException):
        return "timeout" if monotonic() >= deadline else "invalid_response"
    except OSError:
        return "timeout" if monotonic() >= deadline else "unavailable"
    finally:
        timer.cancel()
        if response is not None:
            response.close()
        connection.close()


class HealthProbe:
    """Only one submitted operation, even if every HTTP waiter is cancelled."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="health")
        self._future: asyncio.Future[LLMStatus] | None = None
        self._started = 0.0
        self._closed = False

    async def check(self) -> LLMStatus:
        if self._closed:
            return "unavailable"
        if self._future is None or self._future.done():
            self._started = monotonic()
            self._future = asyncio.get_running_loop().run_in_executor(self._executor, probe, self.origin)
        try:
            return await asyncio.wait_for(asyncio.shield(self._future), max(0.001, 5 - (monotonic() - self._started)))
        except TimeoutError:
            return "timeout"

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
