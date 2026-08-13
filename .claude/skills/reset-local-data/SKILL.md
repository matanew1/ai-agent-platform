---
name: reset-local-data
description: Safely inspect or reset ai-agent-platform's local PostgreSQL, Redis, or Qdrant data. Use when asked to clear local sessions, documents, development data, recreate the database, or drop/reset a local service; never use for production or without explicit confirmation of the exact data to remove.
---

# Reset local data

Treat every reset as destructive. Operate only on the local Docker Compose
services in this repository; never infer that a remote URL or production
environment is in scope.

1. Inspect first: run `docker compose ps` and list the exact target volume(s)
   with `docker volume ls`. State what will be lost and ask for confirmation
   that names the chosen scope before mutating anything.
2. Use the narrowest scope:
   - **Redis only:** `docker compose exec redis redis-cli FLUSHDB`. This clears
     hot cache and locks; durable sessions remain in PostgreSQL and rehydrate.
   - **Qdrant only:** stop `qdrant`, remove only its inspected named volume,
     then start `qdrant`. This permanently removes indexed documents, not the
     PostgreSQL agents/sessions/artifacts.
   - **PostgreSQL only:** stop `postgres`, remove only its inspected named
     volume, start `postgres`, then run `uv run alembic upgrade head`. This
     permanently removes agents, durable sessions, and artifact records.
   - **All local app data:** reset the three named volumes above, then run
     `docker compose up -d` and `uv run alembic upgrade head`.
3. Do not use `docker compose down -v`, broad Docker pruning, wildcard volume
   deletion, or a volume name guessed from the project directory. Preserve
   unrelated containers and volumes.
4. Verify with `docker compose ps`, `uv run alembic current`, and the relevant
   local admin UI (pgAdmin `:8082`, Redis Commander `:8083`, Qdrant dashboard
   `:6333/dashboard`). Report the reset scope and that the data cannot be
   recovered from this local stack.
