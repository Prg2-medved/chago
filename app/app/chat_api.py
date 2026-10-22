"""Strict public request/response contract, with no validation input echo."""

from dataclasses import asdict

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.chat import ChatService


class ChatRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4096)

    @field_validator("session_id", "message")
    @classmethod
    def nonblank(cls, value: str) -> str:
        # Field length constraints have already checked the original, untrimmed string.
        if not value.strip():
            raise ValueError("blank_field")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("invalid_unicode") from None
        return value.strip()


class ChatSource(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    title: str
    heading: str
    url: str
    quote: str


class ChatResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    answer: str
    insufficient_context: bool
    sources: list[ChatSource]


router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    service: ChatService = request.app.state.chat
    result = await service.answer(payload.message)
    return ChatResponse(answer=result.answer, insufficient_context=result.insufficient_context,
                        sources=[ChatSource(**asdict(source)) for source in result.sources])
