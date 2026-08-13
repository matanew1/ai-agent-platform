"""Pydantic request models for the streaming chat route."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatFileAttachment(BaseModel):
    """One file attached to a chat turn.

    Base64 rather than multipart so ``/chat/stream`` keeps one request
    shape (JSON) whether or not a caller sends files - see
    ``chat.controller``. The server derives the authenticated owner and
    selected agent, then indexes the extracted content for later retrieval.
    """

    filename: str
    content_base64: str


class ChatRequest(BaseModel):
    """One chat turn for a configurable agent."""

    session_id: str
    message: str
    files: list[ChatFileAttachment] = Field(default_factory=list)


__all__ = ["ChatFileAttachment", "ChatRequest"]
