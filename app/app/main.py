from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.chat import ChatError, ChatService
from app.chat_api import router
from app.config import load_index_path
from app.index_state import RetrievalService
from app.health import HealthProbe, chat_status, index_snapshot


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    chat_logger = logging.getLogger("app.chat")
    chat_logger.setLevel(logging.INFO)
    if not chat_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        chat_logger.addHandler(handler)
    retrieval = RetrievalService(load_index_path())
    chat = ChatService(retrieval)
    probe = HealthProbe(os.environ.get("LLM_BASE_URL", "http://llm:8080"))
    try:
        await retrieval.start()
        application.state.index = retrieval.state
        application.state.retrieval = retrieval
        application.state.chat = chat
        application.state.health_probe = probe
        yield
    finally:
        probe.close()
        try:
            await chat.close()
        finally:
            await retrieval.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(router)
static = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static), name="static")


@app.middleware("http")
async def no_store(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    if request.url.path in ("/", "/api/chat", "/health"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
    return response


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(static / "index.html")


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Некорректный запрос. Проверьте поля и их длину."})


@app.exception_handler(ChatError)
async def chat_error(request: Request, error: ChatError) -> JSONResponse:
    details = {
        422: "Вопрос превышает допустимый бюджет токенов. Сократите вопрос.",
        502: "Некорректный ответ сервиса генерации.",
        503: "Chat временно недоступен.",
        504: "Превышено время ожидания сервиса генерации.",
    }
    return JSONResponse(status_code=error.status, content={"detail": details[error.status]})


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    status = await request.app.state.health_probe.check()
    return {"status": "ok", "app": {"status": "ok"},
            "index": asdict(index_snapshot(request.app.state.index)),
            "llm": {"status": status}, "chat": {"status": chat_status(request.app.state.chat.gate)}}
