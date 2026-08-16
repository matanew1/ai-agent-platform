"""Pydantic request models for the streaming chat route."""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.limits import (
    MAX_ATTACHMENT_BASE64_CHARS,
    MAX_CHAT_ATTACHMENTS,
    MAX_CHAT_MESSAGE_CHARS,
)


class ChatFileAttachment(BaseModel):
    """One file attached to a chat turn.

    Base64 rather than multipart so ``/chat/stream`` keeps one request
    shape (JSON) whether or not a caller sends files - see
    ``chat.controller``. The server derives the authenticated owner and
    selected agent, then indexes the extracted content for later retrieval.
    """

    filename: str
    content_base64: str = Field(max_length=MAX_ATTACHMENT_BASE64_CHARS)


class ChatRequest(BaseModel):
    """One chat turn for a configurable agent."""

    session_id: str
    message: str = Field(max_length=MAX_CHAT_MESSAGE_CHARS)
    files: list[ChatFileAttachment] = Field(default_factory=list, max_length=MAX_CHAT_ATTACHMENTS)


__all__ = ["ChatFileAttachment", "ChatRequest"]
