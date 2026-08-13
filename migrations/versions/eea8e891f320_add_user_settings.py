"""add user settings

Revision ID: eea8e891f320
Revises: 7eafd694e27c
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eea8e891f320"
down_revision: str | Sequence[str] | None = "7eafd694e27c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the owner-scoped durable settings table."""
    op.create_table(
        "user_settings",
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner_id"),
    )


def downgrade() -> None:
    """Remove the durable settings table."""
    op.drop_table("user_settings")
