import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    llm_base_url: str = "http://llm:8080"
    llm_model_name: str = "Qwen3-4B-Instruct-2507"
    llm_max_tokens: int = 768


def load_settings() -> Settings:
    try:
        port = int(os.environ.get("APP_PORT", "8000"))
    except ValueError:
        raise ValueError("APP_PORT must be an integer between 1 and 65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("APP_PORT must be an integer between 1 and 65535")
    try:
        max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "768"))
    except ValueError:
        raise ValueError("LLM_MAX_TOKENS must be a positive integer") from None
    if max_tokens < 1:
        raise ValueError("LLM_MAX_TOKENS must be a positive integer")
    return Settings(
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=port,
        llm_base_url=os.environ.get("LLM_BASE_URL", "http://llm:8080").rstrip("/"),
        llm_model_name=os.environ.get("LLM_MODEL_NAME", "Qwen3-4B-Instruct-2507"),
        llm_max_tokens=max_tokens,
    )


@dataclass(frozen=True)
class IngestionSettings:
    host: str
    name: str
    user: str
    password: str = field(repr=False)
    source_origin: str
    port: int = 5432
    view: str = "rag.rag_wikijs_pages_v1"
    timeout_seconds: int = 30


def load_ingestion_settings() -> IngestionSettings:
    def required(name: str) -> str:
        value = os.environ.get(name, "")
        if not value.strip() or "\x00" in value:
            raise ValueError(f"configuration: {name} is required")
        return value

    def integer(name: str, default: int, maximum: int) -> int:
        try:
            value = int(os.environ.get(name, str(default)))
        except ValueError:
            raise ValueError(f"configuration: {name} must be an integer in 1..{maximum}") from None
        if not 1 <= value <= maximum:
            raise ValueError(f"configuration: {name} must be an integer in 1..{maximum}")
        return value

    host = required("WIKI_DB_HOST")
    name = required("WIKI_DB_NAME")
    user = required("WIKI_DB_USER")
    password = required("WIKI_DB_PASSWORD")
    view = os.environ.get("WIKI_DB_VIEW", "rag.rag_wikijs_pages_v1")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}", view):
        raise ValueError("configuration: WIKI_DB_VIEW must be schema.view")
    origin = required("WIKI_SOURCE_ORIGIN")
    try:
        parsed = urlsplit(origin)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and "?" not in origin
            and "#" not in origin
            and not any(char.isspace() or ord(char) < 32 for char in origin)
            and "\\" not in origin
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and not parsed.netloc.endswith(":")
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("configuration: WIKI_SOURCE_ORIGIN must be an HTTP(S) origin") from None
    return IngestionSettings(
        host=host,
        name=name,
        user=user,
        password=password,
        source_origin=f"{parsed.scheme}://{parsed.netloc}".rstrip("/"),
        port=integer("WIKI_DB_PORT", 5432, 65535),
        view=view,
        timeout_seconds=integer("WIKI_DB_TIMEOUT_SECONDS", 30, 2147483),
    )
