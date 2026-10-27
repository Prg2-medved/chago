"""7.8 authored fixtures with 7.9 regressions; never invoke a model.

Historical baseline remains in the JSON fixture. Command guard regressions
override it explicitly; uncaught unsafe outputs remain documented gaps, not pass
safety. Prompt-only changes still need live review.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.grounding import (FALLBACK, REFUSAL, Evidence, Fragment,
                           build_messages, parse_generated, validate_answer)


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "grounding-safety-7.8.json").read_text(encoding="utf-8"))
CASES = FIXTURES["cases"]
COMMAND_REGRESSIONS = {
    "clarify-with-hidden-command", "tuning-q03-command-excerpt", "netplan-inline",
    "custom-command-prose", "custom-command-inline", "altered-custom-command-prose",
}


def manifest_for(name, reverse=False):
    items = []
    for item in FIXTURES["manifests"][name]:
        offset = 0
        fragments = []
        for text in item["fragments"]:
            fragments.append(Fragment(offset, offset + len(text), text))
            offset += len(text)
        items.append(Evidence(identity(item["key"]), item["title"], item["heading"],
                              "https://wiki.example/ru/diagnostic/" + item["key"], tuple(fragments)))
    return tuple(reversed(items)) if reverse else tuple(items)


def identity(key):
    return hashlib.sha256(("grounding-safety-7.8:" + key).encode()).hexdigest()


def raw_for(case):
    answer = case["answer"]
    for key in ("A", "B", "Z"):
        answer = answer.replace("$" + key + "$", "[chunk:" + identity(key) + "]")
    return json.dumps({"kind": case["kind"], "answer": answer}, ensure_ascii=False)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("reverse", [False, True], ids=["original-order", "reversed-order"])
def test_validator_regressions_and_remaining_boundaries(case, reverse):
    manifest = manifest_for(case["manifest"], reverse)
    messages = build_messages(case["question"], manifest)
    assert json.loads(messages[1]["content"])["question"] == case["question"]
    assert [item["id"] for item in json.loads(messages[1]["content"])["CONTEXT"]] == [item.chunk_id for item in manifest]
    raw = raw_for(case)
    assert parse_generated(raw).kind == case["kind"]
    errors = []
    result = validate_answer(raw, manifest, on_error=errors.append)
    guarded = case["id"] in COMMAND_REGRESSIONS
    assert result.insufficient_context is (True if guarded else case["baseline_insufficient"])
    assert errors == (["code_prose"] if guarded else [case["baseline_error"]] if "baseline_error" in case else [])
    if guarded or case["baseline"] == "fallback":
        assert result.answer == FALLBACK and result.sources
    elif case["baseline"] == "refuse":
        assert result.answer == REFUSAL and not result.sources
    else:
        assert result.answer not in (FALLBACK, REFUSAL)
        assert len(result.sources) == case["answer"].count("$A$") + case["answer"].count("$B$")


def test_question_is_present_in_prompt_but_not_an_input_to_validator():
    ambiguous, explicit = CASES[:2]
    assert ambiguous["safe"] is False and explicit["safe"] is True
    assert raw_for(ambiguous) == raw_for(explicit)
    manifest = manifest_for("restart")
    assert build_messages(ambiguous["question"], manifest) != build_messages(explicit["question"], manifest)
    # Identical validator inputs yield identical published output for questions
    # that require different safety decisions. No model effectiveness is tested.
    assert validate_answer(raw_for(ambiguous), manifest) == validate_answer(raw_for(explicit), manifest)


def test_citation_and_partial_kind_do_not_establish_conflict_handling():
    partial = next(case for case in CASES if case["id"] == "conflict-selected-partial")
    correct = next(case for case in CASES if case["id"] == "conflict-correct-control")
    manifest = manifest_for("conflict")
    one_side = validate_answer(raw_for(partial), manifest)
    both_sides = validate_answer(raw_for(correct), manifest)
    assert one_side.insufficient_context and both_sides.insufficient_context
    assert len(one_side.sources) == 1 and len(both_sides.sources) == 2
    assert one_side.answer != FALLBACK and both_sides.answer != FALLBACK
