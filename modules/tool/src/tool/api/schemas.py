"""Pydantic models for tool HTTP requests."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """Arguments supplied to a registered tool."""

    arguments: dict[str, object] = Field(default_factory=dict)
