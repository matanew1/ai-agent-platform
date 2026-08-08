"""Pydantic request and response models for customizable-agent routes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

DEFAULT_SYSTEM_PROMPT = """\
You are the ai-agent-platform assistant. Answer using the retrieved context
and tool results provided to you. If you don't have enough information,
say so instead of guessing.
"""


class ChatRequest(BaseModel):
    """One chat turn for a configurable agent."""

    session_id: str
    message: str


class ChatResponse(BaseModel):
    """Completed configurable-agent chat turn."""

    session_id: str
    message: str
    execution_time_seconds: float
    tools_invoked: list[str] = Field(default_factory=list)
    chunks_retrieved: int = 0


class CreateAgentRequest(BaseModel):
    """Fields for a new customizable agent."""

    owner_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, min_length=1, max_length=8_000)
    allowed_tools: list[str] = Field(default_factory=list)


class UpdateAgentRequest(BaseModel):
    """Editable fields for an existing customizable agent."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=8_000)
    allowed_tools: list[str] | None = None


class AgentResponse(BaseModel):
    """Public representation of a persisted configurable agent."""

    id: str
    name: str
    system_prompt: str
    allowed_tools: list[str]
    version: int
    created_at: datetime
    updated_at: datetime
