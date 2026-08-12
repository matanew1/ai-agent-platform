"""Pydantic request models for the streaming chat route."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatFileAttachment(BaseModel):
    """One file attached to a single chat turn.

    Base64 rather than multipart so ``/chat/stream`` keeps one request
    shape (JSON) whether or not a caller sends files - see
    ``chat.controller``. Extracted and used for that turn's answer only,
    never persisted; a caller who wants a file permanently searchable
    should use ``rag.controller``'s document-ingestion routes instead.
    """

    filename: str
    content_base64: str


class ChatRequest(BaseModel):
    """One chat turn for a configurable agent."""

    session_id: str
    message: str
    files: list[ChatFileAttachment] = Field(default_factory=list)


__all__ = ["ChatFileAttachment", "ChatRequest"]
