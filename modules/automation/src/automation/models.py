"""SQLAlchemy records owned by the schedule module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.postgres import Base


class AgentScheduleRecord(Base):
    """Relational representation of one cron-triggered unattended agent run."""

    __tablename__ = "agent_schedules"
    __table_args__ = (Index("ix_agent_schedules_owner_agent", "owner_id", "agent_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    cron_expression: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_message: Mapped[str] = mapped_column(Text, nullable=False)
    # None means "use the agent's own allowed_tools at fire time" - see
    # automation.runner.ScheduleRunner._run_once. When set, always a subset
    # of the agent's allowed_tools (enforced in automation.controller,
    # which is the one place that already has the agent loaded to check
    # against - see its docstring).
    tools: Mapped[list[str] | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_session_id: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
