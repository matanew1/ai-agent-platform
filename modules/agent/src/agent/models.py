"""SQLAlchemy records owned by the agent module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.postgres import Base


class AgentRecord(Base):
    """Relational representation of one versioned agent."""

    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_owner_updated", "owner_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    model: Mapped[str | None] = mapped_column(String(200))
    temperature: Mapped[float | None] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
