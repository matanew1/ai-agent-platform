"""Domain type and Pydantic request/response models for agent schedules."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentSchedule(BaseModel):
    """A cron-triggered unattended run configured for one owned agent.

    Deliberately a sibling concept to ``shared.types.Agent`` rather than a
    field on it: a schedule can be created, paused, or deleted independently
    of editing the agent it targets, and an agent-definition edit (which
    bumps ``Agent.version``) should never force a schedule rewrite. Stays
    local to this module rather than in ``shared/types.py`` since nothing
    outside ``schedule`` needs to know its shape - see
    ``.claude/rules/architecture.md`` on cross-module sharing.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    agent_id: str
    cron_expression: str = Field(min_length=1, max_length=120)
    trigger_message: str = Field(min_length=1, max_length=8_000)
    enabled: bool = True
    next_run_at: datetime
    last_run_at: datetime | None = None
    last_run_session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreateScheduleRequest(BaseModel):
    """Fields for a new schedule on an owned agent."""

    model_config = ConfigDict(extra="forbid")

    cron_expression: str = Field(min_length=1, max_length=120)
    trigger_message: str = Field(min_length=1, max_length=8_000)


class UpdateScheduleRequest(BaseModel):
    """Editable fields for an existing schedule."""

    model_config = ConfigDict(extra="forbid")

    cron_expression: str | None = Field(default=None, min_length=1, max_length=120)
    trigger_message: str | None = Field(default=None, min_length=1, max_length=8_000)
    enabled: bool | None = None


class ScheduleResponse(BaseModel):
    """Public representation of a persisted schedule."""

    id: str
    agent_id: str
    cron_expression: str
    trigger_message: str
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_run_session_id: str | None
    created_at: datetime
    updated_at: datetime
