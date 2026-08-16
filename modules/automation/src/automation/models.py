"""SQLAlchemy records owned by the schedule module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.postgres import Base


class AgentScheduleRecord(Base):
    """Relational representation of one cron-triggered unattended agent run."""

    __tablename__ = "agent_schedules"
    __table_args__ = (Index("ix_agent_schedules_owner_agent", "owner_id", "agent_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_message: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_session_id: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
