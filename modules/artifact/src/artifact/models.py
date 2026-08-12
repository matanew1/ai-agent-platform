"""SQLAlchemy records owned by the artifact module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.postgres import Base


class ArtifactAccessRecord(Base):
    """Ownership grant for one generated artifact filename."""

    __tablename__ = "artifact_access"
    __table_args__ = (Index("ix_artifact_access_user_created", "user_id", "created_at"),)

    filename: Mapped[str] = mapped_column(String(512), primary_key=True)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactContentRecord(Base):
    """A generated artifact's bytes, stored in PostgreSQL instead of local disk.

    Keyed by the same safe filename ``ArtifactAccessRecord`` grants ownership
    over, but written independently (at generation time, before an owner is
    known - see ``artifact.service.ArtifactService``).
    """

    __tablename__ = "artifact_content"

    filename: Mapped[str] = mapped_column(String(512), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
