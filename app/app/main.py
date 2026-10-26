from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.chat import ChatError, ChatService
from app.chat_api import router
from app.config import load_index_path
from app.index_state import RetrievalService


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
    try:
        await retrieval.start()
        application.state.index = retrieval.state
        application.state.retrieval = retrieval
        application.state.chat = chat
        yield
    finally:
        try:
            await chat.close()
        finally:
            await retrieval.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(router)


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
async def health() -> dict[str, str]:
    return {"status": "ok"}
