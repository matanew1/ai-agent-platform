"""Domain type and Pydantic request/response models for feedback submissions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

_MAX_MESSAGE_CHARS = 4_000
_MAX_CONTEXT_PATH_CHARS = 500

FeedbackCategory = Literal["bug", "feedback"]


class Feedback(BaseModel):
    """A submitted bug report or piece of product feedback.

    Deliberately a sibling concept to ``shared.types.Agent``/``automation.
    schemas.AgentSchedule`` rather than living in ``shared/types.py`` - nothing
    outside this module needs to know its shape (see
    ``.claude/rules/architecture.md`` on cross-module sharing).
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    category: FeedbackCategory
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_CHARS)
    context_path: str | None = Field(default=None, max_length=_MAX_CONTEXT_PATH_CHARS)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreateFeedbackRequest(BaseModel):
    """Fields the caller supplies when submitting feedback."""

    model_config = ConfigDict(extra="forbid")

    category: FeedbackCategory
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_CHARS)
    context_path: str | None = Field(default=None, max_length=_MAX_CONTEXT_PATH_CHARS)


class FeedbackResponse(BaseModel):
    """Confirmation of a submitted report - not a readable record; there is no GET."""

    id: str
    created_at: datetime
