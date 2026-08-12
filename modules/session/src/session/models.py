"""SQLAlchemy records owned by the session module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.postgres import Base


class SessionCheckpointRecord(Base):
    """Relational representation of durable chat session history."""

    __tablename__ = "agent_sessions"
    __table_args__ = (Index("ix_agent_sessions_updated_at", "updated_at"),)

    session_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    history: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
