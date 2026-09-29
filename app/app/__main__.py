import sys

import uvicorn

from app.config import load_settings


def main() -> None:
    try:
        settings = load_settings()
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, workers=1)


if __name__ == "__main__":
    main()
