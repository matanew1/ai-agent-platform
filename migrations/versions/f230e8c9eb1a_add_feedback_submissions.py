"""add feedback submissions

Revision ID: f230e8c9eb1a
Revises: 3f7c9a2e5b1d
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f230e8c9eb1a"
down_revision: str | Sequence[str] | None = "3f7c9a2e5b1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the owner-scoped feedback-submissions table."""
    op.create_table(
        "feedback_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context_path", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_submissions_owner_id", "feedback_submissions", ["owner_id"], unique=False
    )


def downgrade() -> None:
    """Remove the feedback-submissions table."""
    op.drop_index("ix_feedback_submissions_owner_id", table_name="feedback_submissions")
    op.drop_table("feedback_submissions")
