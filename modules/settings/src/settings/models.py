from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.postgres import Base


class UserSettingsRecord(Base):
    """One owner-scoped settings document, persisted in PostgreSQL."""

    __tablename__ = "user_settings"

    owner_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    settings: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
