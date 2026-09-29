import os
from dataclasses import dataclass


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
