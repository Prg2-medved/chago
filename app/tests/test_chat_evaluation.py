from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.chat_evaluation import evaluate, fixed_manifest
from app.evaluation import ValidationError
from app.grounding import FALLBACK
from app.llm_client import Completion, LLMError
from test_retrieval_evaluation import evaluation_inputs


class Client:
    def __init__(self):
        self.messages = []

    def count_prompt(self, messages):
        return 100

    def fits(self, count):
        return count + 768 <= 8192

    def complete(self, messages):
        self.messages.append(messages)
        content = json.loads(messages[1]["content"])["CONTEXT"]
        return Completion(json.dumps({"kind": "answer", "answer": "Answer [chunk:" + content[0]["id"] + "]"}), 100)


def run(inputs, mode, client=None, **kwargs):
    package, live, synthetic = inputs
    def adapter(index):
        return SimpleNamespace(snapshot=index.snapshot, search=lambda question: index.search(question, 6))
    return evaluate(*package.paths[:3], package.paths[3], client or Client(), mode=mode,
                    indices={"live": adapter(live), "synthetic": adapter(synthetic)}, **kwargs)


@pytest.mark.parametrize("mode", ["end-to-end", "generation-only"])
def test_frozen_identity_no_followup_no_writes_and_separate_sources(evaluation_inputs, mode):
    package, live, synthetic = evaluation_inputs
    before = [path.read_bytes() for path in package.paths]
    report = run(evaluation_inputs, mode)
    expected = [case for case in package.corpus["questions"] if "follow_up" not in case["tags"]]
    assert [row["id"] for row in report["cases"]] == [case["id"] for case in expected]
    assert not report["follow_up_acceptance"] and report["manual_review_required"]
    assert report["fingerprints"]["questions"] == hashlib.sha256(before[0]).hexdigest()
    assert before == [path.read_bytes() for path in package.paths]
    assert set(row["source_set"] for row in report["cases"]) == {"live", "synthetic"}
    assert all(row["manual_verdict"] == "pending" for row in report["cases"])
    assert all(row["token_count_matches"] for row in report["cases"] if row["packed_ids"])
    assert all(row["validation_error"] is None for row in report["cases"])
    if mode == "generation-only":
        assert not live.calls and not synthetic.calls
        assert all(row["supplied_evidence_complete"] is not False for row in report["cases"])
    else:
        assert all("\n" not in query for query in live.calls + synthetic.calls)


def test_fixed_ranges_stable_ids_namespace_and_exact_slices(evaluation_inputs):
    package, _, _ = evaluation_inputs
    case = package.corpus["questions"][0]
    manifest, pages = fixed_manifest(case, package.live)
    assert fixed_manifest(case, package.live) == (manifest, pages)
    for item, evidence in zip(manifest, case["evidence"], strict=True):
        assert [f.text for f in item.fragments] == [span["exact_text"] for span in evidence["spans"]]
    changed = dict(case, source_set="other_namespace")
    assert fixed_manifest(changed, package.live)[0][0].chunk_id != manifest[0].chunk_id


def test_index_identity_mismatch_stops_before_generation(evaluation_inputs):
    package, live, synthetic = evaluation_inputs
    live.snapshot = replace(live.snapshot, source="https://other.example")
    client = Client()
    with pytest.raises(ValidationError, match="index source inventory"):
        run(evaluation_inputs, "end-to-end", client)
    assert not client.messages and not live.calls


def test_no_retry_or_next_case_after_timeout(evaluation_inputs):
    client = Client()
    def fail(messages):
        client.messages.append(messages)
        raise LLMError("llm_timeout", 504, generation_uncertain=True)
    client.complete = fail
    with pytest.raises(LLMError):
        run(evaluation_inputs, "generation-only", client)
    assert len(client.messages) == 1


def test_case_selection_does_not_change_fingerprints_or_accept_followup(evaluation_inputs):
    package, _, _ = evaluation_inputs
    selected = package.corpus["questions"][0]["id"]
    report = run(evaluation_inputs, "generation-only", case_ids=[selected])
    assert [row["id"] for row in report["cases"]] == [selected]
    with pytest.raises(ValidationError, match="unknown or follow-up"):
        run(evaluation_inputs, "generation-only", case_ids=["not-a-case"])


@pytest.mark.parametrize("content,category", [
    ("PRIVATE_INVALID_OUTPUT", "generated_json"),
    (json.dumps({"kind": "answer", "answer": "PRIVATE_INVALID_OUTPUT"}), "citation_missing"),
    (json.dumps({"kind": "answer", "answer": "PRIVATE_INVALID_OUTPUT [chunk:bad]"}), "citation_marker"),
    (json.dumps({"kind": "answer", "answer": "```sh\nPRIVATE_INVALID_OUTPUT\n```"}), "code_source"),
    (json.dumps({"kind": "clarify", "answer": "PRIVATE_INVALID_OUTPUT sudo systemctl restart atlas?"}), "code_prose"),
])
def test_validation_diagnostic_preserves_fallback_without_publishing_raw_output(evaluation_inputs, content, category):
    client = Client()
    def invalid(messages):
        client.messages.append(messages)
        return Completion(content, 100)
    client.complete = invalid
    selected = evaluation_inputs[0].corpus["questions"][0]["id"]
    emitted = []
    report = run(evaluation_inputs, "generation-only", client, case_ids=[selected], on_case=emitted.append)
    row = report["cases"][0]
    assert row["validation_error"] == category and row["validation_fallback"]
    assert row["response"]["answer"] == FALLBACK and row["response"]["insufficient_context"]
    assert row["response"]["sources"]
    assert "PRIVATE_INVALID_OUTPUT" not in json.dumps(emitted)
    assert emitted == report["cases"] and len(client.messages) == 1
