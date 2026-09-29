import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str
    port: int


def load_settings() -> Settings:
    try:
        port = int(os.environ.get("APP_PORT", "8000"))
    except ValueError:
        raise ValueError("APP_PORT must be an integer between 1 and 65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("APP_PORT must be an integer between 1 and 65535")
    return Settings(host=os.environ.get("APP_HOST", "127.0.0.1"), port=port)
