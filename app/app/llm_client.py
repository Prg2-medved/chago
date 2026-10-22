"""Blocking internal llama.cpp transport, run by the chat worker, without retries."""

from collections.abc import Sequence
from dataclasses import dataclass
import http.client
import json
import socket
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.config import ChatSettings


class Message(TypedDict):
    role: str
    content: str


class LLMError(ValueError):
    def __init__(self, category: str, status: int, *, generation_uncertain: bool = False) -> None:
        super().__init__(category)
        self.category = category
        self.status = status
        self.generation_uncertain = generation_uncertain


@dataclass(frozen=True)
class Completion:
    content: str
    prompt_tokens: int | None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class LLMClient:
    def __init__(self, settings: ChatSettings) -> None:
        settings.__post_init__()
        try:
            url = urlsplit(settings.base_url)
            valid = (url.scheme in {"http", "https"} and bool(url.hostname)
                     and not url.path and not url.query and not url.fragment
                     and url.username is None and url.password is None
                     and (url.port is None or 1 <= url.port <= 65535)
                     and not any(c.isspace() or ord(c) < 32 for c in settings.base_url)
                     and "\\" not in settings.base_url and not url.netloc.endswith(":"))
            if not valid or not settings.model_name.strip():
                raise ValueError
        except ValueError:
            raise LLMError("llm_configuration", 503) from None
        self.settings = settings
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _post(self, path: str, payload: dict[str, Any], *, completion: bool = False) -> dict[str, Any]:
        try:
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            request = Request(self.settings.base_url + path, data=data,
                              headers={"Content-Type": "application/json", "Accept": "application/json"})
        except (ValueError, UnicodeError, TypeError):
            raise LLMError("llm_request", 503) from None
        try:
            with self._opener.open(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read()
                if response.status != 200:
                    raise LLMError("llm_protocol", 502)
        except HTTPError as error:
            error.close()
            # An explicit HTTP rejection is distinct from an uncertain socket loss.
            raise LLMError("llm_unavailable" if error.code >= 500 else "llm_protocol",
                           503 if error.code >= 500 else 502) from None
        except (TimeoutError, URLError, OSError, http.client.HTTPException) as error:
            reason = error.reason if isinstance(error, URLError) else error
            timeout = isinstance(reason, TimeoutError)
            before_send = isinstance(reason, (ConnectionRefusedError, socket.gaierror))
            raise LLMError("llm_timeout" if timeout else "llm_unavailable", 504 if timeout else 503,
                           generation_uncertain=completion and not before_send) from None
        # A fully received response confirms the transport ended, even if its
        # JSON/envelope/content is invalid. No uncertain slot for protocol errors.
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeError):
            raise LLMError("llm_protocol", 502) from None

    def count_prompt(self, messages: Sequence[Message]) -> int:
        prompt = self._post("/apply-template", {"messages": messages, "add_generation_prompt": True}).get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise LLMError("llm_template_protocol", 502)
        tokens = self._post("/tokenize", {"content": prompt, "add_special": True,
                                         "parse_special": True, "with_pieces": False}).get("tokens")
        if not isinstance(tokens, list) or not tokens or any(type(token) is not int for token in tokens):
            raise LLMError("llm_token_protocol", 502)
        return len(tokens)

    def fits(self, prompt_tokens: int) -> bool:
        return prompt_tokens + self.settings.max_tokens <= self.settings.context_size

    def complete(self, messages: Sequence[Message]) -> Completion:
        result = self._post("/v1/chat/completions", {
            "model": self.settings.model_name, "messages": messages, "stream": False,
            "max_tokens": self.settings.max_tokens, "temperature": self.settings.temperature,
            "top_p": self.settings.top_p, "top_k": self.settings.top_k, "cache_prompt": False,
        }, completion=True)
        try:
            content = result["choices"][0]["message"]["content"]
            if result.get("model") != self.settings.model_name or not isinstance(content, str) or not content.strip():
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise LLMError("llm_completion_protocol", 502) from None
        usage = result.get("usage")
        count = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        return Completion(content, count if type(count) is int and count >= 0 else None)
