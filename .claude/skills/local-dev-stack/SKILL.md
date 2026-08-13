---
name: local-dev-stack
description: Bring up, verify, and troubleshoot ai-agent-platform's local PostgreSQL, Redis, Qdrant, Ollama, and FastAPI development environment.
---

# Run ai-agent-platform locally

1. Copy `.env.example` to `.env` if it does not exist, then run `uv sync`.
2. Start local dependencies with `docker compose up -d`:
   - PostgreSQL `:5432` (durable agents, sessions, artifact ownership)
   - Redis `:6379` (hot cache and locks)
   - Qdrant `:6333` / `:6334` (RAG vectors)
   - pgAdmin `:8082`, Redis Commander `:8083`, Qdrant dashboard
     `:6333/dashboard` (local inspection only)
3. Pull `qwen3:8b` and `bge-m3` from Ollama when they are not already
   installed. Run migrations with `uv run alembic upgrade head`, then start
   the API with `uv run app`. Confirm `GET http://localhost:8000/health`.

## Day-to-day checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
```

Set `LOG_LEVEL=DEBUG` to inspect lifecycle, Redis, PostgreSQL, Qdrant, and
tool activity without logging prompts or document contents.

## Troubleshooting

- **Startup cannot connect:** run `docker compose ps`; verify `DATABASE_URL`,
  `REDIS_URL`, and `QDRANT_URL` match the Compose ports.
- **Embedding dimensions changed:** use a new `QDRANT_COLLECTION` or explicitly
  reset and re-ingest local vectors with `$reset-local-data`.
- **First turn is slow:** agent runtimes compile lazily per agent definition;
  later turns reuse the cached runtime.
