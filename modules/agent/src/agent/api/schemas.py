"""Private admin/test request and response models for the core agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """One direct private-admin turn against the core agent workflow."""

    session_id: str
    message: str
    tools: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Completed private-admin agent turn."""

    session_id: str
    message: str
    execution_time_seconds: float
    tools_invoked: list[str] = Field(default_factory=list)
    chunks_retrieved: int = 0
