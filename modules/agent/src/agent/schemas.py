"""Pydantic request and response models for agent-definition and session routes.

Chat-turn schemas live in ``chat.schemas``, document-library schemas live
in ``rag.schemas``, and model-catalog schemas live in ``model.schemas`` -
see each module's own controller.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shared.types import ChatMessage

DEFAULT_SYSTEM_PROMPT = """\
You are the ai-agent-platform assistant. Answer using the retrieved context
and tool results provided to you. Use an available tool when its stated
purpose directly matches the user's request; prefer its result over an
unsupported estimate. Never invent, hallucinate, or imply facts, tool calls,
tool results, sources, files, download links, or external services. If you
don't have enough information, say so plainly instead of guessing.
"""


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


class SessionResponse(BaseModel):
    """One persisted client session and its complete retained history."""

    session_id: str
    history: list[ChatMessage]
    updated_at: datetime
