# ai-agent-platform

## Working model

This repository is the FastAPI backend for the sibling React client at
`../ai-agent-platform-web`. It is a Python 3.12 `uv` workspace. The local
stack is PostgreSQL (durable agents, sessions, and artifact ownership), Redis
(hot cache and locks), Qdrant (user-scoped RAG vectors), and Ollama.

`app/lifespan.py` is the composition root: it builds infrastructure clients
and module services once and exposes them through `app.state`. Keep routes
thin; they validate HTTP input, derive the authenticated user, call a service,
and map a result to HTTP.

Modules own distinct concerns:

- `agent`: agent definitions and session HTTP surface.
- `chat` and `graph`: streamed turn execution and prompt workflow.
- `rag`: document extraction, indexing, and retrieval.
- `session`: PostgreSQL checkpoints with Redis cache/locking.
- `artifact`: generated-file ownership and download authorization.
- `authentication`, `model`, and `tool`: identity, model catalog, and local/MCP tools.

## Non-negotiable conventions

- Use the authenticated `CurrentUser` as the only ownership source. Check an
  agent/resource belongs to that user before reading or writing it. Never add
  a caller-controlled `owner_id` field.
- Chat files are both immediate prompt attachments and durable RAG documents.
  Preserve the internal source ID for access/deletion; the web client may
  format it for display only.
- Keep vendor SDKs in `infrastructure/`; translate their errors before they
  escape an API boundary. Use a `Protocol` only when there is a genuine
  boundary or more than one useful implementation—do not introduce a future
  abstraction speculatively.
- Add migrations for PostgreSQL schema changes and run `uv run alembic upgrade
  head` locally. Redis is not the source of truth for sessions.
- Do not log prompt, document, or response contents. Log only safe IDs,
  lengths, and counts.
- Preserve dirty worktree changes. Do not reset or delete local data without
  the user's explicit confirmation of the target; use `$reset-local-data`.

## Verification

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
```

For a backend change consumed by the web app, also run `npm run build` in
`../ai-agent-platform-web`; use `$full-stack-change` for the contract
checklist. A new streamed metadata header must be listed in the CORS
`expose_headers` configuration and parsed defensively by the web client.

## Available workflows

- `$local-dev-stack`: start or diagnose the local services.
- `$reset-local-data`: safely clear an explicit local data scope.
- `$full-stack-change`: coordinate backend and web-client work.
- `$git-ship`: intentional branch, conventional commits, review, PR, version
  bump, and release workflow.
- `.claude/agents/architect.md` and `.claude/agents/code-reviewer.md`: design
  and implementation review roles.
