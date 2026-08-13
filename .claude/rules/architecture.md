# Architecture Rules

## Source of truth

Read `app/lifespan.py` before changing service construction. It is the sole
composition root: infrastructure clients and module services are built once
per process there and exposed to request handlers through `app.state`.

The workspace modules have concrete responsibilities:

- `agent`: definitions and agent/session API.
- `chat` + `graph`: streamed turns, prompt preparation, and response state.
- `rag`: document ingestion and Qdrant-backed retrieval.
- `session`: PostgreSQL checkpoints plus Redis hot cache/locking.
- `artifact`, `authentication`, `model`, `tool`: artifacts, identity, model
  catalog, and local/MCP tool execution.

`infrastructure/` owns vendor adapters (PostgreSQL, Redis, Qdrant, Ollama)
and provider-neutral failures. `shared/` may not depend on modules or
infrastructure.

## Boundaries

- Put HTTP parsing, authentication dependencies, and response construction in
  a module controller. Put use-case orchestration in a service. Do not create
  a service from a request handler.
- Let modules depend on a capability abstraction where that boundary exists;
  keep SDK-specific types behind `infrastructure/`. Do not add an interface,
  factory, or module solely for a hypothetical future implementation.
- `app/main.py` only mounts routers and configures process-wide middleware;
  cross-module wiring belongs in `app/lifespan.py`.
- Preserve user ownership at every boundary. `CurrentUser` is authoritative;
  user IDs are never accepted from request payloads. Documents are user-scoped
  in Qdrant, sessions are user-and-agent-scoped in PostgreSQL, and Redis is
  never the durable source of session truth.

## Data and external effects

- Use Alembic for PostgreSQL schema changes. Do not create tables ad hoc at
  request time.
- Chat attachments are extracted for the immediate prompt and indexed into
  the authenticated user's RAG library for future retrieval. Keep internal
  source IDs separate from display labels.
- Vendor failures must be translated into `PlatformError`-compatible errors
  before the HTTP boundary. Log safe IDs, counts, and lengths—not prompts,
  documents, tokens, or secrets.
- A new MCP/local tool is a security decision. Keep the handler typed, avoid
  raw filesystem/shell access from model input, and update the tool registry
  only in `app/lifespan.py`.
