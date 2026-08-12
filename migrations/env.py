"""Alembic migration environment.

Async because the app's own engine is (``infrastructure.database.postgres``
uses ``asyncpg``) - mirrors Alembic's own async-template pattern rather than
the sync default ``alembic init`` scaffolds.

``DATABASE_URL`` is read the same way the app itself reads it
(``app/lifespan.py``'s default), so migrations always target whatever
database the app would actually connect to - not a second, driftable
copy of the URL hardcoded in ``alembic.ini``.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

# Import every module that defines a SQLAlchemy model so Base.metadata
# actually knows about all of them before autogenerate compares against
# it - each of these registers its tables on import as a side effect of
# subclassing infrastructure.database.postgres.Base.
import agent.models  # noqa: F401
import artifact.models  # noqa: F401
import session.models  # noqa: F401
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from infrastructure.database.postgres import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Overrides alembic.ini's sqlalchemy.url when DATABASE_URL is set - the
# ini value stays only as a sane local-dev default (matches
# app/lifespan.py's own default) for anyone running alembic without a
# fully configured environment yet.
if database_url := os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Emit SQL without a live DB connection (``alembic upgrade head --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
