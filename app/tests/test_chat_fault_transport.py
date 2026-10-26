"""The operator boundary must send once, preserve payload, and hide responses."""

import importlib.util
import json
from pathlib import Path
import threading
from urllib.request import HTTPHandler, ProxyHandler, build_opener

import pytest

from app.llm_client import LLMError
from test_llm_client import MESSAGES, envelope, http_llm


SPEC = importlib.util.spec_from_file_location(
    "chat_fault", Path(__file__).resolve().parents[2] / "docs/grounded-chat-api-fault.py")
assert SPEC and SPEC.loader
fault = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fault)


@pytest.mark.parametrize("mode", ["release", "timeout"])
def test_boundary_forwards_once_and_withholds_only_first_completion(http_llm, tmp_path, mode):
    client, calls, replies = http_llm
    boundary = fault.Boundary(tmp_path, mode)

    class Handler(HTTPHandler):
        def http_open(self, req):
            return self.do_open(boundary.connection, req)

    client._opener = build_opener(ProxyHandler({}), Handler())
    replies.extend([(200, {"prompt": "template"}, 0), (200, {"tokens": [1]}, 0),
                    (200, envelope("SECRET_GENERATED"), 0), (200, envelope(), 0)])
    assert client.count_prompt(MESSAGES) == 1
    results = []
    def complete():
        try:
            results.append(client.complete(MESSAGES))
        except LLMError as error:
            results.append(error)
    thread = threading.Thread(target=complete)
    thread.start()
    try:
        assert boundary.sent.wait(2)
        assert not results
        assert boundary.count == 1
        if mode == "release":
            (tmp_path / "release").touch()
        thread.join(3)
        assert not thread.is_alive()
        if mode == "timeout":
            assert isinstance(results[0], LLMError)
            assert results[0].status == 504 and results[0].generation_uncertain
        else:
            assert results[0].content == "SECRET_GENERATED"
        # A further send is observable; the boundary never silently hides it.
        assert client.complete(MESSAGES).content == "answer"
        assert boundary.count == 2
        assert [path for path, _ in calls] == [
            "/apply-template", "/tokenize", "/v1/chat/completions", "/v1/chat/completions"]
        assert calls[2][1]["messages"] == MESSAGES
        trace = (tmp_path / "trace.jsonl").read_text()
        events = [json.loads(line) for line in trace.splitlines()]
        assert [event["count"] for event in events if event["event"] == "upstream_completion_sent"] == [1, 2]
        assert "SECRET" not in trace and "Вопрос" not in trace
    finally:
        (tmp_path / "release").touch()
        thread.join(3)
