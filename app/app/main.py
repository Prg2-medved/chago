from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import load_index_path
from app.index_state import RetrievalService


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    retrieval = RetrievalService(load_index_path())
    try:
        await retrieval.start()
        application.state.index = retrieval.state
        application.state.retrieval = retrieval
        yield
    finally:
        await retrieval.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
