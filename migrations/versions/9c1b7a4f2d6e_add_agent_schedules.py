"""add agent schedules

Revision ID: 9c1b7a4f2d6e
Revises: eea8e891f320
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c1b7a4f2d6e"
down_revision: str | Sequence[str] | None = "eea8e891f320"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the owner-and-agent-scoped cron schedule table."""
    op.create_table(
        "agent_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("cron_expression", sa.String(length=120), nullable=False),
        sa.Column("trigger_message", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_session_id", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_schedules_owner_agent", "agent_schedules", ["owner_id", "agent_id"])


def downgrade() -> None:
    """Remove the cron schedule table."""
    op.drop_index("ix_agent_schedules_owner_agent", table_name="agent_schedules")
    op.drop_table("agent_schedules")
