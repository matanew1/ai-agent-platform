"""Domain type and Pydantic request/response models for agent schedules."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.limits import MAX_CHAT_MESSAGE_CHARS

_MAX_TITLE_CHARS = 200
_MAX_DESCRIPTION_CHARS = 1000


class AgentSchedule(BaseModel):
    """A cron-triggered unattended run configured for one owned agent.

    Deliberately a sibling concept to ``shared.types.Agent`` rather than a
    field on it: a schedule can be created, paused, or deleted independently
    of editing the agent it targets, and an agent-definition edit (which
    bumps ``Agent.version``) should never force a schedule rewrite. Stays
    local to this module rather than in ``shared/types.py`` since nothing
    outside ``automation`` needs to know its shape - see
    ``.claude/rules/architecture.md`` on cross-module sharing.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    agent_id: str
    title: str = Field(min_length=1, max_length=_MAX_TITLE_CHARS)
    description: str | None = Field(default=None, max_length=_MAX_DESCRIPTION_CHARS)
    cron_expression: str = Field(min_length=1, max_length=120)
    # trigger_message becomes a ChatService.run_stream message just like an
    # interactive turn (see automation.runner), so it reuses the same bound
    # rather than inventing a second, drifting number - see shared/limits.py.
    trigger_message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    # None means "use the agent's own allowed_tools at fire time" - a
    # non-None value narrows that set for this schedule only, and is
    # validated as a subset of the agent's allowed_tools at the one place
    # that already has the agent loaded to check against - see
    # automation.controller's docstring on why that validation lives there
    # rather than here or in ScheduleService.
    tools: list[str] | None = None
    enabled: bool = True
    next_run_at: datetime
    last_run_at: datetime | None = None
    last_run_session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreateScheduleRequest(BaseModel):
    """Fields for a new schedule on an owned agent."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=_MAX_TITLE_CHARS)
    description: str | None = Field(default=None, max_length=_MAX_DESCRIPTION_CHARS)
    cron_expression: str = Field(min_length=1, max_length=120)
    trigger_message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    tools: list[str] | None = None


class UpdateScheduleRequest(BaseModel):
    """Editable fields for an existing schedule.

    ``agent_id``, if present, moves the schedule to a different agent
    the same caller owns - validated in ``automation.controller`` (the
    request's URL path still names the schedule's *current* agent; this
    field is the new target, see the controller's own docstring for the
    ownership check and the tools-reconciliation that comes with a move).
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=_MAX_TITLE_CHARS)
    description: str | None = Field(default=None, max_length=_MAX_DESCRIPTION_CHARS)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=120)
    trigger_message: str | None = Field(
        default=None, min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS
    )
    tools: list[str] | None = None
    enabled: bool | None = None


class ScheduleResponse(BaseModel):
    """Public representation of a persisted schedule."""

    id: str
    agent_id: str
    title: str
    description: str | None
    cron_expression: str
    trigger_message: str
    tools: list[str] | None
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_run_session_id: str | None
    created_at: datetime
    updated_at: datetime
