"""Administrative live gate 7.1 for final chat messages and exact context boundaries."""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
import sys
from time import monotonic
from urllib.request import Request

from app.config import load_chat_settings, load_embedding_settings, load_index_path, load_retrieval_settings
from app.embeddings import LocalEncoder
from app.grounding import Evidence, Fragment, PackedContext, build_manifest, build_messages, pack_context
from app.hybrid_retrieval import HybridIndex
from app.index_state import ActiveIndex
from app.llm_client import LLMClient, LLMError


BOUNDARY_QUESTION = "Ответь одним словом по CONTEXT."


def boundary_manifest(words: int) -> tuple[Evidence, ...]:
    text = " x" * words
    return (Evidence("f" * 64, "Diagnostic boundary fixture", "", "https://wiki.example/boundary",
                     (Fragment(0, len(text), text),)),)


def find_boundary(client: LLMClient, target: int) -> PackedContext:
    """Every candidate is counted by llama.cpp; no estimated or corrected counts."""
    low, high = 1, 1
    while client.count_prompt(build_messages(BOUNDARY_QUESTION, boundary_manifest(high))) < target:
        high *= 2
        if high > client.settings.context_size * 16:
            raise ValueError("token_boundary_unreachable")
    while low <= high:
        middle = (low + high) // 2
        manifest = boundary_manifest(middle)
        messages = build_messages(BOUNDARY_QUESTION, manifest)
        count = client.count_prompt(messages)
        if count == target:
            return PackedContext(manifest, messages, count)
        if count < target:
            low = middle + 1
        else:
            high = middle - 1
    raise ValueError("token_boundary_unreachable")


def verify_completion(name: str, packed: PackedContext, client: LLMClient) -> None:
    started = monotonic()
    completion = client.complete(packed.messages)
    equal = packed.prompt_tokens == completion.prompt_tokens
    print(json.dumps({"case": name, "calculated": packed.prompt_tokens, "actual": completion.prompt_tokens,
                      "equal": equal, "max_tokens": client.settings.max_tokens,
                      "context_size": client.settings.context_size,
                      "packed_ids": [item.chunk_id for item in packed.manifest],
                      "elapsed_seconds": round(monotonic() - started, 3)}, ensure_ascii=False), flush=True)
    if not equal or not client.fits(packed.prompt_tokens):
        raise ValueError("final_token_count_mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        digests = json.loads(os.environ["ACCEPTANCE_IMAGE_DIGESTS"])
        model_hash = os.environ["ACCEPTANCE_MODEL_SHA256"]
        expected_image = "ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283"
        if (expected_image not in digests
                or model_hash != "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e"):
            raise ValueError("identity_mismatch")
        settings = load_chat_settings()
        client = LLMClient(settings)
        with client._opener.open(Request(settings.base_url + "/props"), timeout=settings.timeout_seconds) as response:
            props = json.load(response)
        if props["default_generation_settings"]["n_ctx"] != settings.context_size:
            raise ValueError("context_mismatch")
        print(json.dumps({"image_digests": digests, "model_sha256": model_hash,
                          "model_alias": settings.model_name, "context_size": settings.context_size,
                          "max_tokens": settings.max_tokens, "timeout_seconds": settings.timeout_seconds,
                          "chat_template_sha256": hashlib.sha256(json.dumps(props["chat_template"], ensure_ascii=False).encode()).hexdigest()},
                         ensure_ascii=False), flush=True)
        path = load_index_path()
        def fingerprint() -> str:
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        before = fingerprint()
        encoder = LocalEncoder(load_embedding_settings())
        with ActiveIndex(path) as active:
            with HybridIndex._from_active(active, encoder, load_retrieval_settings()) as index:
                question = "Как работает роутплан?"
                results = index.search(question)
                packed = pack_context(question, build_manifest([result.chunk for result in results]), client)
                if not packed.manifest:
                    raise ValueError("missing_final_prompt_evidence")
                print(json.dumps({"index_sha256": before, "index_metadata": asdict(active.metadata),
                                  "retrieved_ids": [result.chunk.chunk_id for result in results]}, ensure_ascii=False), flush=True)
                verify_completion("final_retrieved_prompt", packed, client)
        target = settings.context_size - settings.max_tokens
        at_boundary = find_boundary(client, target)
        verify_completion("prompt_plus_reserve_equals_window", at_boundary, client)
        overflow = find_boundary(client, target + 1)
        packed_overflow = pack_context(BOUNDARY_QUESTION, overflow.manifest, client)
        if client.fits(overflow.prompt_tokens) or packed_overflow.manifest:
            raise ValueError("overflow_packing_mismatch")
        after = fingerprint()
        if before != after:
            raise ValueError("index_changed")
        print(json.dumps({"gate_7_1": "passed", "overflow_calculated": overflow.prompt_tokens,
                          "overflow_completion_sent": False, "overflow_context_removed_whole": True,
                          "index_unchanged": True}), flush=True)
    except LLMError as error:
        print(json.dumps({"gate_7_1": "NOT_PASSED", "error": error.category,
                          "generation_uncertain": error.generation_uncertain,
                          "action": "stop; no retry; confirm previous generation ended"}), file=sys.stderr)
        return 1
    except Exception:
        print("gate 7.1 NOT_PASSED: identity/assets/index/context/token compatibility", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
