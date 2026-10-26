#!/usr/bin/env python3
"""Test-only Compose entrypoint: withhold completion response, never retry.

The real request is sent once to the unchanged local LLM. Only the first
completion is intercepted. No response bytes are consumed until release;
timeout mode waits the configured transport timeout and raises TimeoutError.
SIGUSR1 cancels the first chat ASGI task after that send (not the LLM thread).
No HTTP control endpoints, generated content or credentials in the trace.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any
from urllib.request import HTTPHandler


class Boundary:
    def __init__(self, directory: Path, mode: str) -> None:
        self.directory = directory
        self.mode = mode
        self.sent = threading.Event()
        self.lock = threading.Lock()
        self.count = 0

    def record(self, event: str, **fields: Any) -> None:
        with self.lock:
            with (self.directory / "trace.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps({"event": event, "utc": datetime.now(timezone.utc).isoformat(),
                                         "monotonic": time.monotonic(), **fields}) + "\n")

    def connection(self, host: str, **kwargs: Any) -> http.client.HTTPConnection:
        boundary = self

        class Connection(http.client.HTTPConnection):
            intercepted = False

            def request(self, method: str, url: str, body: Any = None,
                        headers: Any = None, *, encode_chunked: bool = False) -> None:
                super().request(method, url, body, headers or {}, encode_chunked=encode_chunked)
                if url == "/v1/chat/completions":
                    with boundary.lock:
                        boundary.count += 1
                        count = boundary.count
                    self.intercepted = count == 1
                    boundary.record("upstream_completion_sent", count=count)
                    boundary.sent.set()

            def getresponse(self) -> http.client.HTTPResponse:
                if self.intercepted:
                    assert self.timeout is not None
                    timeout = float(self.timeout)
                    boundary.record("response_withheld", timeout_seconds=timeout)
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        if boundary.mode == "release" and (boundary.directory / "release").exists():
                            boundary.record("response_read_released")
                            return super().getresponse()
                        time.sleep(min(.1, max(0, deadline - time.monotonic())))
                    boundary.record("transport_timeout")
                    raise TimeoutError
                return super().getresponse()

        return Connection(host, **kwargs)


def main() -> None:
    if sys.platform != "linux":
        raise SystemExit("run_on_linux_compose_host")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--mode", choices=("release", "timeout"), required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # A directory is single-use, so stale controls can never release a new fault.
    with (directory / "trace.jsonl").open("x", encoding="utf-8"):
        pass
    if (directory / "release").exists():
        raise SystemExit("stale_release_control")

    import uvicorn
    from app import llm_client
    from app.chat import ChatService
    from app.config import load_chat_settings, load_settings
    from app.main import app

    settings = load_chat_settings()
    if not settings.base_url.startswith("http://"):
        raise SystemExit("fault_requires_internal_http_origin")
    boundary = Boundary(directory, args.mode)

    class Handler(HTTPHandler):
        def http_open(self, req: Any) -> Any:
            return self.do_open(boundary.connection, req)

    original_opener = llm_client.build_opener
    llm_client.build_opener = lambda *handlers: original_opener(*handlers, Handler())
    original_answer = ChatService.answer
    first_task: asyncio.Task[Any] | None = None

    async def answer(self: ChatService, question: str) -> Any:
        nonlocal first_task
        if first_task is None:
            first_task = asyncio.current_task()
            loop = asyncio.get_running_loop()

            def cancel() -> None:
                if boundary.sent.is_set() and first_task is not None and not first_task.done():
                    boundary.record("asgi_task_cancelled")
                    first_task.cancel()
                else:
                    boundary.record("cancellation_rejected")

            loop.add_signal_handler(getattr(signal, "SIGUSR1"), cancel)
        return await original_answer(self, question)

    setattr(ChatService, "answer", answer)
    server = load_settings()
    boundary.record("startup", mode=args.mode, timeout_seconds=settings.timeout_seconds)
    uvicorn.run(app, host=server.host, port=server.port, workers=1)


if __name__ == "__main__":
    main()
