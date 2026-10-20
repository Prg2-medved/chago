from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import load_index_path
from app.index_state import load_index_state


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    state = load_index_state(load_index_path())
    application.state.index = state
    try:
        yield
    finally:
        state.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
