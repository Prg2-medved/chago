"""Read-only, stdlib-only integrity validation of a frozen evaluation package."""

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import TypeAlias
from urllib.parse import quote, urlsplit


Json: TypeAlias = "None | bool | int | float | str | list[Json] | dict[str, Json]"
Object: TypeAlias = dict[str, Json]
REQUIRED_TAGS = frozenset({
    "text", "identifier", "code", "table", "follow_up", "refuse", "partial_answer",
    "clarify", "long_code", "similar_identifiers", "prompt_injection", "conflict", "composite",
})
STARTER_QUESTIONS = frozenset({
    "Как работает роутплан?", "Как настроить сервер?",
    "Как настроить сервер на объекте?", "Какое оборудование используется в складе?",
})
BEHAVIOR_TAGS = {"refuse": "refuse", "clarify": "clarify",
                 "partial_answer": "partial_answer", "report_conflict": "conflict"}


class ValidationError(ValueError):
    """Only controlled diagnostics; never include untrusted source values."""


@dataclass(frozen=True)
class ValidationReport:
    corpus_version: int
    questions: int
    documents: dict[str, int]
    fingerprints: dict[str, str]
    categories: dict[str, int]
    splits: dict[str, int]


def require(condition: bool, category: str, location: str) -> None:
    if not condition:
        raise ValidationError(f"{category}: {location}")


def obj(value: Json, location: str) -> Object:
    require(isinstance(value, dict), "type", location)
    if isinstance(value, dict):
        return value
    raise AssertionError


def array(value: Json, location: str) -> list[Json]:
    require(isinstance(value, list), "type", location)
    if isinstance(value, list):
        return value
    raise AssertionError


def string(value: Json, location: str, *, empty: bool = False) -> str:
    require(isinstance(value, str) and (empty or bool(value.strip())), "type", location)
    if isinstance(value, str):
        return value
    raise AssertionError


def integer(value: Json, location: str, minimum: int = 1) -> int:
    require(type(value) is int, "type", location)
    if type(value) is int:
        require(value >= minimum, "value", location)
        return value
    raise AssertionError


def digest(value: Json, location: str) -> str:
    result = string(value, location)
    require(re.fullmatch(r"[0-9a-f]{64}", result) is not None, "hash", location)
    return result


def strings(value: Json, location: str, *, nonempty: bool = False) -> list[str]:
    result = [string(item, location) for item in array(value, location)]
    require(len(result) == len(set(result)) and (not nonempty or bool(result)), "value", location)
    return result


def unique_pairs(pairs: list[tuple[str, Json]]) -> Object:
    result: Object = {}
    for key, value in pairs:
        require(key not in result, "format", "duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value: str) -> Json:
    raise ValidationError("format: nonfinite JSON number")


def full_command(command: str, text: str, start: int, stop: int) -> bool:
    """Require complete source lines, including multiline commands, not a prefix."""
    offset = text.find(command)
    while offset >= 0:
        end = offset + len(command)
        before = text[text.rfind("\n", 0, offset) + 1:offset]
        line_end = text.find("\n", end)
        after = text[end:line_end if line_end >= 0 else len(text)]
        if (start <= offset and end <= stop
                and not before.strip(" \t\r") and not after.strip(" \t\r")):
            return True
        offset = text.find(command, offset + 1)
    return False


def read_json(path: Path, role: str) -> tuple[Object, bytes]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise ValidationError(f"file: {role}") from None
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                             parse_constant=invalid_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ValidationError(f"format: {role} (UTF-8 JSON-compatible YAML/JSON required)") from None
    return obj(payload, role), raw


def version(payload: Object, location: str) -> None:
    require(integer(payload.get("schema_version"), location) == 1, "version", location)


def source_origin(value: Json, location: str) -> str:
    source = string(value, location)
    try:
        parts = urlsplit(source)
        valid = (parts.scheme in ("http", "https") and bool(parts.hostname)
                 and parts.username is None and parts.password is None
                 and not parts.path and not parts.query and not parts.fragment
                 and parts.port != 0)
    except ValueError:
        valid = False
    require(valid, "source", location)
    return source


def load_snapshot(path: Path, entry: Object, namespace: str) -> tuple[dict[int, Object], str]:
    snapshot, raw = read_json(path, namespace)
    version(snapshot, namespace)
    source = source_origin(snapshot.get("source"), namespace)
    require(source == source_origin(entry.get("source"), namespace), "source", namespace)
    fingerprint = hashlib.sha256(raw).hexdigest()
    require(fingerprint == digest(entry.get("sha256"), namespace), "fingerprint", namespace)
    count = integer(entry.get("document_count"), namespace)
    docs = array(snapshot.get("documents"), namespace)
    require(len(docs) == count, "inventory", namespace)
    actual: dict[int, Object] = {}
    identities: set[tuple[str, str]] = set()
    for index, item in enumerate(docs, 1):
        loc = f"{namespace} document#{index}"
        d = obj(item, loc)
        page_id = integer(d.get("page_id"), loc)
        require(page_id not in actual, "duplicate", loc)
        locale, document_path = (string(d.get(k), loc) for k in ("locale", "path"))
        require((locale, document_path) not in identities, "duplicate", loc)
        identities.add((locale, document_path))
        string(d.get("title"), loc)
        url = string(d.get("source_url"), loc)
        require(url == f"{source}/{quote(locale, safe='')}/{quote(document_path, safe='/')}", "source", loc)
        timestamp = string(d.get("updated_at"), loc)
        require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", timestamp) is not None,
                "metadata", loc)
        try:
            require(datetime.fromisoformat(timestamp).utcoffset() is not None, "metadata", loc)
        except ValueError:
            raise ValidationError(f"metadata: {loc}") from None
        markdown = string(d.get("markdown"), loc, empty=True)
        require(hashlib.sha256(markdown.encode("utf-8")).hexdigest() == digest(d.get("content_sha256"), loc), "content_hash", loc)
        actual[page_id] = d
    inventory = array(entry.get("documents"), namespace)
    require(len(inventory) == count, "inventory", namespace)
    seen: set[int] = set()
    for item in inventory:
        d = obj(item, namespace)
        page_id = integer(d.get("page_id"), namespace)
        require(page_id not in seen and page_id in actual, "inventory", namespace)
        seen.add(page_id)
        for field in ("locale", "path", "content_sha256"):
            string(d.get(field), namespace)
            require(d[field] == actual[page_id][field], "inventory", namespace)
    return actual, fingerprint


def validate_package(questions: Path, manifest: Path, snapshot: Path,
                     fixtures: Path | None = None) -> ValidationReport:
    corpus, _ = read_json(questions, "questions")
    metadata, _ = read_json(manifest, "manifest")
    version(corpus, "questions")
    version(metadata, "manifest")
    corpus_version = integer(metadata.get("corpus_version"), "manifest")
    require(integer(corpus.get("corpus_version"), "questions") == corpus_version, "version", "corpus")
    cases = array(corpus.get("questions"), "questions")
    require(bool(cases), "coverage", "empty corpus")
    sources: dict[str, dict[int, Object]] = {}
    fingerprints: dict[str, str] = {}
    sources["live"], fingerprints["live"] = load_snapshot(snapshot, obj(metadata.get("live"), "live"), "live")
    synthetic = any(obj(q, "question").get("source_set") == "synthetic" for q in cases)
    if synthetic or "synthetic" in metadata or fixtures is not None:
        require(fixtures is not None and "synthetic" in metadata, "fixtures", "synthetic inputs required")
        if fixtures is not None:
            entry = obj(metadata.get("synthetic"), "synthetic")
            require(entry.get("source") != obj(metadata.get("live"), "live").get("source"), "source", "namespaces")
            sources["synthetic"], fingerprints["synthetic"] = load_snapshot(fixtures, entry, "synthetic")
    ids: set[str] = set()
    tags_count: Counter[str] = Counter()
    splits: Counter[str] = Counter()
    behavior_count: Counter[str] = Counter()
    answer_splits: Counter[str] = Counter()
    starters: set[str] = set()
    for index, item in enumerate(cases, 1):
        # An invalid ID may contain credentials, so only echo constrained stable IDs.
        loc = f"question#{index}"
        q = obj(item, loc)
        case_id = string(q.get("id"), loc)
        require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", case_id) is not None, "id", loc)
        loc = case_id
        require(case_id not in ids, "duplicate", loc)
        ids.add(case_id)
        question = string(q.get("question"), loc)
        starters.add(question)
        tags = strings(q.get("tags"), loc, nonempty=True)
        require(set(tags) <= REQUIRED_TAGS, "coverage", loc)
        tags_count.update(tags)
        split = string(q.get("split"), loc)
        namespace = string(q.get("source_set"), loc)
        require(split in ("tuning", "holdout"), "split", loc)
        require(namespace in sources, "source", loc)
        splits[f"{namespace}/{split}"] += 1
        behavior = string(q.get("expected_behavior"), loc)
        require(behavior in ("answer", "partial_answer", "refuse", "clarify", "report_conflict"), "behavior", loc)
        require(type(q.get("answerable")) is bool, "type", loc)
        answerable = q["answerable"]
        require(answerable == (behavior in ("answer", "partial_answer", "report_conflict")), "behavior", loc)
        behavior_count[behavior] += 1
        answer_splits[f"{split}/{answerable}"] += 1
        for expected, tag in BEHAVIOR_TAGS.items():
            require((tag in tags) == (behavior == expected), "behavior", loc)
        if "follow_up" in tags:
            string(q.get("previous_question"), loc)
        else:
            require("previous_question" not in q, "behavior", loc)
        if behavior == "partial_answer":
            string(q.get("missing_information"), loc)
        if behavior == "clarify":
            string(q.get("clarification"), loc)
        facts = array(q.get("required_facts"), loc)
        evidence = array(q.get("evidence"), loc)
        commands = strings(q.get("exact_commands"), loc)
        require((1 <= len(facts) <= 3 and bool(evidence)) if answerable else
                (not facts and not evidence and not commands), "behavior", loc)
        evidence_ids: set[str] = set()
        evidence_pages: set[int] = set()
        source_regions: list[tuple[str, int, int]] = []
        for item_evidence in evidence:
            e = obj(item_evidence, loc)
            eid = string(e.get("id"), loc)
            require(eid not in evidence_ids, "duplicate", loc)
            evidence_ids.add(eid)
            page_id = integer(e.get("page_id"), loc)
            require(page_id in sources[namespace], "missing_page", loc)
            evidence_pages.add(page_id)
            d = sources[namespace][page_id]
            for field in ("locale", "path", "content_sha256"):
                string(e.get(field), loc)
                require(e[field] == d[field], "identity", loc)
            if "heading_path" in e:
                strings(e["heading_path"], loc, nonempty=True)
            spans = array(e.get("spans"), loc)
            require(bool(spans), "span", loc)
            markdown = string(d.get("markdown"), loc, empty=True)
            for item_span in spans:
                span = obj(item_span, loc)
                start = integer(span.get("start"), loc, 0)
                end = integer(span.get("end"), loc, 0)
                exact = string(span.get("exact_text"), loc)
                require(0 <= start < end <= len(markdown), "span", loc)
                require(markdown[start:end] == exact, "exact_text", loc)
                source_regions.append((markdown, start, end))
        referenced: set[str] = set()
        for item_fact in facts:
            fact = obj(item_fact, loc)
            string(fact.get("text"), loc)
            references = strings(fact.get("evidence_ids"), loc, nonempty=True)
            require(set(references) <= evidence_ids, "fact_reference", loc)
            referenced.update(references)
        require(referenced == evidence_ids, "fact_reference", loc)
        for command in commands:
            require(any(full_command(command, text, start, end)
                        for text, start, end in source_regions), "exact_command", loc)
        if "composite" in tags or behavior == "report_conflict":
            require(len(evidence_pages) >= 2, "coverage", loc)
    require(REQUIRED_TAGS <= set(tags_count), "coverage", "required categories")
    require(STARTER_QUESTIONS <= starters, "coverage", "starter questions")
    require(tags_count["follow_up"] >= 2 and 3 <= behavior_count["refuse"] <= 5, "coverage", "follow-up/refusal quotas")
    require(sum(v for k, v in splits.items() if k.endswith("/holdout")) >= 4
            and answer_splits["holdout/True"] > 0 and answer_splits["holdout/False"] > 0
            and answer_splits["tuning/True"] > 0, "split", "holdout/tuning coverage")
    return ValidationReport(corpus_version, len(cases), {key: len(value) for key, value in sources.items()},
                            fingerprints, dict(sorted(tags_count.items())), dict(sorted(splits.items())))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate frozen evaluation corpus offline (read-only)")
    for option in ("questions", "manifest", "snapshot"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--fixtures", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate_package(args.questions, args.manifest, args.snapshot, args.fixtures)
    except ValidationError as error:
        print(f"evaluation: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"corpus_version": report.corpus_version, "questions": report.questions,
                      "documents": report.documents, "fingerprints": report.fingerprints,
                      "categories": report.categories, "splits": report.splits}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
