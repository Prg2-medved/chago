"""Preregistered tuning-only selection helpers; no holdout loading or inference."""

from collections.abc import Sequence
from typing import Any

from app.evaluation import ValidationError


def summarize_candidate(report: dict[str, Any], baseline: dict[str, Any], *,
                        algorithm: str, literal_policy: int,
                        semantic_candidates: int, lexical_candidates: int) -> dict[str, Any]:
    settings = {"semantic_candidates": semantic_candidates, "lexical_candidates": lexical_candidates,
                "rrf_constant": 60, "top_k": 6}
    if report["requested_split"] != "tuning" or any(case["split"] != "tuning" for case in report["cases"]):
        raise ValidationError("quality: tuning only")
    if report["effective_settings"] != settings or report["policy_versions"] != {"query": 1, "literal": literal_policy}:
        raise ValidationError("quality: settings identity")
    for index in report["indices"].values():
        if index["algorithm_version"] != algorithm or index["identity"]["lexical"]["literal_policy_version"] != literal_policy:
            raise ValidationError("quality: policy identity")
    for key in ("questions", "manifest", "live_reference", "synthetic_reference"):
        if report["fingerprints"][key] != baseline["fingerprints"][key]:
            raise ValidationError("quality: protected fingerprint")
    cases = [case for case in report["cases"] if case["source_set"] == "live" and case["answerable"] and not case["follow_up"]]
    legacy = [case for case in baseline["cases"] if case["source_set"] == "live" and case["answerable"] and not case["follow_up"]]
    if {case["id"] for case in cases} != {case["id"] for case in legacy}:
        raise ValidationError("quality: denominator")
    hits = sorted(case["id"] for case in cases if case["hit"])
    legacy_hits = {case["id"] for case in legacy if case["hit"]}
    lost = sorted(legacy_hits - set(hits))
    return {"algorithm": algorithm, "literal_policy": literal_policy, "settings": settings,
            "count": len(cases), "hits": len(hits), "hit_ids": hits,
            "miss_ids": sorted(case["id"] for case in cases if not case["hit"]),
            "lost_legacy_hit_ids": lost, "new_hit_ids": sorted(set(hits) - legacy_hits),
            "follow_up_hits": sum(bool(case["hit"]) for case in report["cases"]
                                  if case["source_set"] == "live" and case["answerable"] and case["follow_up"]),
            "changed_policies": int(algorithm != "markdown-chunking-1") + int(literal_policy != 1),
            "fingerprints": report["fingerprints"], "peak_memory_bytes": report["peak_memory_bytes"],
            "warm_mean_seconds": sum(case["warm_duration_seconds"] for case in report["cases"]) / len(report["cases"])}


def select_candidate(candidates: Sequence[dict[str, Any]]) -> dict[str, Any]:
    eligible = [candidate for candidate in candidates if candidate["mandatory_development_checks_passed"]]
    if not eligible:
        raise ValidationError("quality: no eligible candidate")
    def order(candidate: dict[str, Any]) -> tuple[Any, ...]:
        settings = candidate["settings"]
        return (-candidate["hits"], bool(candidate["lost_legacy_hit_ids"]), -candidate["follow_up_hits"],
                candidate["changed_policies"], settings["semantic_candidates"] + settings["lexical_candidates"],
                settings["semantic_candidates"], candidate["algorithm"], str(candidate["literal_policy"]))
    return min(eligible, key=order)
