"""Pydantic request and response models for agent-definition and chat routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.types import ChatMessage

DEFAULT_SYSTEM_PROMPT = """\
You are the ai-agent-platform assistant. Answer using the retrieved context
and tool results provided to you. If you don't have enough information,
say so instead of guessing.
"""


class ChatFileAttachment(BaseModel):
    """One file attached to a single chat turn.

    Base64 rather than multipart so ``/chat/stream`` keeps one request
    shape (JSON) whether or not a caller sends files - see
    ``agent.api.router``'s chat route. Extracted and used for that turn's
    answer only, never persisted; a caller who wants a file permanently
    searchable should use the document-ingestion routes instead.
    """

    filename: str
    content_base64: str


class ChatRequest(BaseModel):
    """One chat turn for a configurable agent."""

    session_id: str
    message: str
    files: list[ChatFileAttachment] = Field(default_factory=list)


class CreateAgentRequest(BaseModel):
    """Fields for a new customizable agent."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, min_length=1, max_length=8_000)
    allowed_tools: list[str] = Field(default_factory=list)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)


class UpdateAgentRequest(BaseModel):
    """Editable fields for an existing customizable agent."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=8_000)
    allowed_tools: list[str] | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)


class AgentResponse(BaseModel):
    """Public representation of a persisted configurable agent."""

    id: str
    name: str
    description: str | None
    system_prompt: str
    allowed_tools: list[str]
    model: str | None
    temperature: float | None
    version: int
    created_at: datetime
    updated_at: datetime


class ModelOptionResponse(BaseModel):
    """One provider-native model selectable for an agent."""

    id: str
    label: str


class TemperatureOptionsResponse(BaseModel):
    """Supported per-agent sampling-temperature controls."""

    min: float
    max: float
    step: float
    default: float


class ModelCatalogResponse(BaseModel):
    """Provider-aware defaults and model options for agent configuration."""

    provider: str
    default_model: str
    models: list[ModelOptionResponse]
    temperature: TemperatureOptionsResponse


class IngestDocumentRequest(BaseModel):
    """Text document content to add to one owner's shared knowledge base."""

    source_id: str
    text: str
    chunk_size: int = Field(default=500, gt=0)
    chunk_overlap: int = Field(default=50, ge=0)


class IngestDocumentResponse(BaseModel):
    """Result of indexing one owner-scoped document."""

    source_id: str
    chunks_indexed: int


class DocumentResponse(BaseModel):
    """One source currently available in an owner's document index."""

    source_id: str
    chunks_indexed: int
    status: Literal["indexed"] = "indexed"


class SessionResponse(BaseModel):
    """One persisted client session and its complete retained history."""

    session_id: str
    history: list[ChatMessage]
    updated_at: datetime
