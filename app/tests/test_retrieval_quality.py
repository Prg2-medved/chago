from copy import deepcopy

import pytest

from app.evaluation import ValidationError
from app.retrieval_quality import select_candidate, summarize_candidate


def candidate(hits=7, lost=None, changed=0, s=10, l=1, follow=1, passed=True):
    return {"hits": hits, "lost_legacy_hit_ids": lost or [], "changed_policies": changed,
            "settings": {"semantic_candidates": s, "lexical_candidates": l}, "follow_up_hits": follow,
            "algorithm": "markdown-chunking-1", "literal_policy": 1,
            "mandatory_development_checks_passed": passed}


def test_more_hits_with_losses_eligible_and_boolean_tie_break():
    clean, more = candidate(), candidate(8, ["old"], changed=2, s=120)
    assert select_candidate([clean, more]) is more
    assert select_candidate([candidate(8, follow=0), more])["lost_legacy_hit_ids"] == []
    one, two = candidate(lost=["a"], s=120), candidate(lost=["a", "b"], s=10)
    assert select_candidate([one, two]) is two  # Both have losses; do not minimize loss count.
    assert select_candidate([more, clean]) is more
    assert select_candidate([more, candidate(9, passed=False)]) is more


def test_followup_complexity_limits_order():
    assert select_candidate([candidate(follow=0), candidate(changed=2)])["changed_policies"] == 2
    assert select_candidate([candidate(changed=1), candidate(changed=0, s=120)])["changed_policies"] == 0
    assert select_candidate([candidate(s=40, l=1), candidate(s=10, l=20)])["settings"]["semantic_candidates"] == 10
    with pytest.raises(ValidationError):
        select_candidate([candidate(passed=False)])


def report():
    return {"requested_split": "tuning", "cases": [
        {"id": "one", "split": "tuning", "source_set": "live", "answerable": True,
         "follow_up": False, "hit": True, "warm_duration_seconds": .1}],
        "effective_settings": {"semantic_candidates": 10, "lexical_candidates": 1, "rrf_constant": 60, "top_k": 6},
        "policy_versions": {"query": 1, "literal": 2}, "indices": {"live": {
            "algorithm_version": "markdown-chunking-2", "identity": {"lexical": {"literal_policy_version": 2}}}},
        "fingerprints": {key: "f" for key in ("questions", "manifest", "live_reference", "synthetic_reference")},
        "peak_memory_bytes": 100}


def summarize(value, baseline):
    return summarize_candidate(value, baseline, algorithm="markdown-chunking-2", literal_policy=2,
                               semantic_candidates=10, lexical_candidates=1)


@pytest.mark.parametrize("failure", ["split", "case_split", "settings", "policy", "algorithm", "fingerprint", "denominator"])
def test_split_policy_settings_fingerprints_denominator(failure):
    value = report()
    baseline = deepcopy(value)
    if failure == "split":
        value["requested_split"] = "all"
    elif failure == "case_split":
        value["cases"][0]["split"] = "holdout"
    elif failure == "settings":
        value["effective_settings"]["top_k"] = 5
    elif failure == "policy":
        value["policy_versions"]["literal"] = 1
    elif failure == "algorithm":
        value["indices"]["live"]["algorithm_version"] = "markdown-chunking-1"
    elif failure == "fingerprint":
        value["fingerprints"]["questions"] = "changed"
    else:
        value["cases"][0]["id"] = "different"
    with pytest.raises(ValidationError):
        summarize(value, baseline)


def test_summary_uses_only_tuning_without_loading_files():
    value = report()
    summary = summarize(value, value)
    assert summary["count"] == summary["hits"] == 1
    assert summary["lost_legacy_hit_ids"] == []
