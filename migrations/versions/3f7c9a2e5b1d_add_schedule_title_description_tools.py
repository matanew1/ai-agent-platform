"""add schedule title, description, tools

Revision ID: 3f7c9a2e5b1d
Revises: 9c1b7a4f2d6e
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f7c9a2e5b1d"
down_revision: str | Sequence[str] | None = "9c1b7a4f2d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_TITLE = "Untitled schedule"


def upgrade() -> None:
    """Add title/description/tools to agent_schedules.

    ``title`` is required going forward, but existing rows predate the
    column - backfill them with a placeholder via ``server_default``
    (dropped immediately after) rather than leaving the column nullable,
    the same one-time-backfill shape as a NOT NULL column added after a
    table already has rows.
    """
    op.add_column(
        "agent_schedules",
        sa.Column("title", sa.String(length=200), nullable=False, server_default=_DEFAULT_TITLE),
    )
    op.alter_column("agent_schedules", "title", server_default=None)
    op.add_column("agent_schedules", sa.Column("description", sa.String(length=1000)))
    op.add_column("agent_schedules", sa.Column("tools", sa.JSON()))


def downgrade() -> None:
    """Remove title/description/tools from agent_schedules."""
    op.drop_column("agent_schedules", "tools")
    op.drop_column("agent_schedules", "description")
    op.drop_column("agent_schedules", "title")
