"""SQLAlchemy record owned by the feedback module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.postgres import Base


class FeedbackRecord(Base):
    """One submitted bug report or piece of product feedback."""

    __tablename__ = "feedback_submissions"
    __table_args__ = (Index("ix_feedback_submissions_owner_id", "owner_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # The page/route the submitter was on, purely for triage context - never
    # prompt/document/response content, so safe to store and log alongside
    # the id (see .claude/rules/python-style.md's logging policy).
    context_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
