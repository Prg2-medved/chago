"""Administrative smoke checks; no requests run on application startup."""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from app.config import load_settings

QUESTION = "Ответь по-русски в двух коротких предложениях: почему зимой бывает снег?"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("health", "completion"))
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        url = urlsplit(settings.llm_base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.path
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError("LLM_BASE_URL must be an HTTP origin without /v1 or credentials")
        if not settings.llm_model_name.strip():
            raise ValueError("LLM_MODEL_NAME must not be empty")
        completion = args.command == "completion"
        payload = None
        if completion:
            payload = json.dumps({
                "model": settings.llm_model_name,
                "messages": [{"role": "user", "content": QUESTION}],
                "stream": False,
                "max_tokens": settings.llm_max_tokens,
                "temperature": 0.2,
                "top_p": 0.8,
                "top_k": 20,
            }, ensure_ascii=False).encode("utf-8")
        path = "/v1/chat/completions" if completion else "/health"
        request = Request(
            settings.llm_base_url + path,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        # Local service traffic must not inherit a machine's HTTP proxy settings.
        opener = build_opener(ProxyHandler({}))
        started = time.perf_counter()
        with opener.open(request, timeout=300 if completion else 5) as response:
            if response.status != 200:
                raise ValueError(f"Unexpected HTTP status: {response.status}")
            result = json.load(response)
        elapsed = time.perf_counter() - started
        if not isinstance(result, dict):
            raise ValueError("LLM response must be a JSON object")
        if not completion:
            if result.get("status") != "ok":
                raise ValueError("LLM is not ready: expected status=ok")
            print(json.dumps({"status": "ok"}))
            return 0
        try:
            answer = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("LLM response has no message content") from None
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("LLM returned empty message content")
        if result.get("model") != settings.llm_model_name:
            raise ValueError("Response model does not match LLM_MODEL_NAME alias")
        print(json.dumps({
            "model": result["model"],
            "question": QUESTION,
            "answer": answer,
            "usage": result.get("usage"),
            "timings": result.get("timings"),
            "http_elapsed_seconds": elapsed,
        }, ensure_ascii=False, indent=2))
        return 0
    except HTTPError as error:
        message = "LLM is loading or unavailable" if error.code == 503 else "LLM HTTP error"
        print(f"{message}: HTTP {error.code}", file=sys.stderr)
    except (URLError, OSError, ValueError) as error:
        print(f"LLM check failed: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
