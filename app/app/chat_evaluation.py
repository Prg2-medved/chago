"""Read-only administrative single-question chat evaluation; no public context injection."""

import argparse
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic
from typing import Any, Protocol, cast

from app.config import load_chat_settings, load_embedding_settings, load_retrieval_settings
from app.evaluation import ValidationError, read_json, validate_package
from app.grounding import (FALLBACK, REFUSAL, Evidence, Fragment, GroundedAnswer, TokenCounter,
                           build_manifest, pack_context, validate_answer)
from app.llm_client import Completion, LLMClient, LLMError, Message
from app.retrieval_evaluation import _hash_inputs, covers


class EvaluationClient(TokenCounter, Protocol):
    def complete(self, messages: Sequence[Message]) -> Completion: ...


def fixed_manifest(case: dict[str, Any], reference: dict[str, Any]) -> tuple[tuple[Evidence, ...], dict[str, int]]:
    """Use only frozen required ranges, with stable source-namespaced IDs."""
    documents = {doc["page_id"]: doc for doc in reference["documents"]}
    manifest, pages = [], {}
    for evidence in case["evidence"]:
        doc = documents[evidence["page_id"]]
        if any(doc[key] != evidence[key] for key in ("locale", "path", "content_sha256")):
            raise ValidationError("chat evaluation: evidence identity")
        identity = [case["source_set"], reference["source"], case["id"], evidence["id"], evidence]
        chunk_id = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        fragments = tuple(Fragment(span["start"], span["end"], doc["markdown"][span["start"]:span["end"]])
                          for span in evidence["spans"])
        if any(fragment.text != span["exact_text"] for fragment, span in zip(fragments, evidence["spans"], strict=True)):
            raise ValidationError("chat evaluation: evidence ranges")
        manifest.append(Evidence(chunk_id, doc["title"], " > ".join(evidence.get("heading_path", [])),
                                 doc["source_url"], fragments))
        pages[chunk_id] = doc["page_id"]
    return tuple(manifest), pages


def evidence_complete(case: dict[str, Any], manifest: tuple[Evidence, ...], pages: dict[str, int]) -> bool | None:
    if not case["evidence"]:
        return None
    ranges: dict[int, list[tuple[int, int]]] = {}
    for item in manifest:
        ranges.setdefault(pages[item.chunk_id], []).extend((fragment.start, fragment.end) for fragment in item.fragments)
    return all(covers(ranges.get(evidence["page_id"], []), span["start"], span["end"])
               for evidence in case["evidence"] for span in evidence["spans"])


def evaluate(questions: Path, manifest_path: Path, snapshot: Path, fixtures: Path | None,
             client: EvaluationClient, *, mode: str, indices: dict[str, Any] | None = None,
             index_paths: dict[str, Path] | None = None, case_ids: Sequence[str] = (),
             on_case: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    if mode not in {"end-to-end", "generation-only"}:
        raise ValidationError("chat evaluation: mode")
    inputs = {"questions": questions, "manifest": manifest_path, "live_reference": snapshot}
    if fixtures is not None:
        inputs["synthetic_reference"] = fixtures
    inputs.update({f"{name}_index": path for name, path in (index_paths or {}).items()})
    fingerprints = _hash_inputs(inputs)
    integrity = validate_package(questions, manifest_path, snapshot, fixtures)
    corpus = cast(dict[str, Any], read_json(questions, "questions")[0])
    references = {"live": cast(dict[str, Any], read_json(snapshot, "snapshot")[0])}
    if fixtures is not None:
        references["synthetic"] = cast(dict[str, Any], read_json(fixtures, "fixtures")[0])
    if mode == "end-to-end":
        for namespace, reference in references.items():
            index = (indices or {}).get(namespace)
            if (index is None or index.snapshot.source != reference["source"]
                    or {doc.page_id: asdict(doc) for doc in index.snapshot.documents}
                    != {doc["page_id"]: doc for doc in reference["documents"]}):
                raise ValidationError("chat evaluation: index source inventory")
    selected = [case for case in corpus["questions"] if "follow_up" not in case["tags"]
                and (not case_ids or case["id"] in case_ids)]
    if case_ids and set(case_ids) != {case["id"] for case in selected}:
        raise ValidationError("chat evaluation: unknown or follow-up case")
    cases = []
    for case in selected:
        started = monotonic()
        if mode == "generation-only":
            manifest, pages = fixed_manifest(case, references[case["source_set"]])
            retrieved_ids: list[str] = []
        else:
            index = (indices or {})[case["source_set"]]
            results = index.search(case["question"])
            manifest = build_manifest([result.chunk for result in results])
            pages = {result.chunk.chunk_id: result.chunk.document.page_id for result in results}
            retrieved_ids = [result.chunk.chunk_id for result in results]
        retrieval_ms = (monotonic() - started) * 1000
        supplied_complete = evidence_complete(case, manifest, pages)
        budget_started = monotonic()
        packed = pack_context(case["question"], manifest, client)
        budget_ms = (monotonic() - budget_started) * 1000
        generation_started = monotonic()
        completion = client.complete(packed.messages) if packed.manifest else None
        generation_ms = (monotonic() - generation_started) * 1000
        validation_errors: list[str] = []
        answer = (validate_answer(completion.content, packed.manifest, on_error=validation_errors.append)
                  if completion else GroundedAnswer(REFUSAL, True, ()))
        packed_complete = evidence_complete(case, packed.manifest, pages)
        row = {"id": case["id"], "source_set": case["source_set"], "split": case["split"],
               "answerable": case["answerable"], "expected_behavior": case["expected_behavior"],
               "retrieved_ids": retrieved_ids, "supplied_ids": [item.chunk_id for item in manifest],
               "packed_ids": [item.chunk_id for item in packed.manifest],
               "supplied_evidence_complete": supplied_complete, "packed_evidence_complete": packed_complete,
               "diagnostic": "retrieval_miss" if supplied_complete is False and mode == "end-to-end"
                             else "context_miss" if packed_complete is False else "review_generation",
               "prompt_tokens": packed.prompt_tokens, "actual_prompt_tokens": completion.prompt_tokens if completion else None,
               "token_count_matches": completion.prompt_tokens == packed.prompt_tokens if completion else None,
               "validation_fallback": answer.answer == FALLBACK,
               "validation_error": validation_errors[0] if validation_errors else None,
               "response": asdict(answer),
               "timings_ms": {"retrieval": retrieval_ms, "budget": budget_ms, "generation": generation_ms,
                              "total": (monotonic() - started) * 1000},
               "manual_verdict": "pending"}
        cases.append(row)
        if on_case is not None:
            on_case(row)
    if _hash_inputs(inputs) != fingerprints:
        raise ValidationError("chat evaluation: inputs changed")
    return {"protocol": "grounded-single-question-v1", "mode": mode,
            "corpus_version": integrity.corpus_version, "fingerprints": fingerprints,
            "follow_up_acceptance": False, "cases": cases, "manual_review_required": True}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("end-to-end", "generation-only"), required=True)
    for name in ("questions", "manifest", "snapshot"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("fixtures", "index", "synthetic-index"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        settings = load_chat_settings()
        with ExitStack() as stack:
            indices: dict[str, Any] = {}
            paths: dict[str, Path] = {}
            if args.mode == "end-to-end":
                if args.index is None or (args.fixtures is not None and args.synthetic_index is None):
                    raise ValidationError("chat evaluation: required indices")
                from app.embeddings import LocalEncoder
                from app.hybrid_retrieval import HybridIndex
                encoder = LocalEncoder(load_embedding_settings())
                for name, path in (("live", args.index), ("synthetic", args.synthetic_index)):
                    if path is not None:
                        indices[name] = stack.enter_context(HybridIndex(path, encoder, load_retrieval_settings()))
                        paths[name] = path
            def emit(row: dict[str, Any]) -> None:
                print(json.dumps({"case": row}, ensure_ascii=False, allow_nan=False), flush=True)
            report = evaluate(args.questions, args.manifest, args.snapshot, args.fixtures, LLMClient(settings),
                              mode=args.mode, indices=indices, index_paths=paths, case_ids=args.case, on_case=emit)
            report.pop("cases")
            report["settings"] = {key: value for key, value in asdict(settings).items() if key != "base_url"}
            print(json.dumps({"summary": report}, ensure_ascii=False, allow_nan=False), flush=True)
    except LLMError as error:
        print(json.dumps({"error": error.category, "generation_uncertain": error.generation_uncertain,
                          "action": "stop; no retry; confirm remote generation ended before another run"}), file=sys.stderr)
        return 1
    except Exception:
        print("chat evaluation: invalid inputs or unavailable dependencies", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
