from dataclasses import replace
import json

import pytest

from app.chat_token_check import BOUNDARY_QUESTION, find_boundary, verify_completion
from app.config import ChatSettings
from app.grounding import pack_context
from app.llm_client import Completion


class Counter:
    settings = ChatSettings(context_size=300, max_tokens=10)

    def count_prompt(self, messages):
        context = json.loads(messages[1]["content"])["CONTEXT"]
        return 200 + (len(context[0]["fragments"][0]) // 2 if context else 0)

    def fits(self, count):
        return count + self.settings.max_tokens <= self.settings.context_size

    def complete(self, messages):
        return Completion("synthetic", self.count_prompt(messages))


def test_final_prompt_boundary_equality_and_one_token_overflow(capsys):
    client = Counter()
    boundary = find_boundary(client, 290)
    assert boundary.prompt_tokens == 290 and client.fits(290)
    verify_completion("equal", boundary, client)
    assert json.loads(capsys.readouterr().out)["equal"]
    overflow = find_boundary(client, 291)
    assert not client.fits(291)
    assert not pack_context(BOUNDARY_QUESTION, overflow.manifest, client).manifest


def test_final_boundary_mismatch_or_unreachable_stops():
    client = Counter()
    with pytest.raises(ValueError, match="unreachable"):
        find_boundary(client, 199)
    boundary = find_boundary(client, 290)
    client.complete = lambda messages: Completion("synthetic", 289)
    with pytest.raises(ValueError, match="mismatch"):
        verify_completion("mismatch", boundary, client)
