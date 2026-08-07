# ai-agent-platform

A modular-monolith AI agent platform: FastAPI + LangGraph agent orchestration,
RAG retrieval, and a local tool registry, backed by MongoDB, Redis, and Qdrant.

**`agent`, `rag`, and `tool` are all fully implemented** - a real LangGraph
workflow ([`retrieve_context` ∥ `execute_tools`] → `generate_answer`; the
first two run in parallel, since neither depends on the other's output)
calling a real local LLM via Ollama, real retrieval against a real Qdrant
collection (ingest via `POST /rag/documents`/`POST /rag/documents/file`,
search via `POST /rag/search`), and a real local tool registry (pdf/markdown
extraction). All three are verified against live services, not just unit
tests - see "How to run" below. **`infrastructure/database.py`'s CRUD
methods** (`find_one`/`insert_one`/`update_one`) are the one remaining
scaffold - nothing in the current request path calls them, so nothing is
actually blocked on it; `connect`/`close` are real. See `.claude/rules/` for
the conventions this project follows, `CLAUDE.md` for the project-wide
summary, and [`CHANGELOG.md`](CHANGELOG.md) (Keep a Changelog +
Semantic Versioning) for release history.

## Project structure

```
ai-agent-platform/
├── app/                    # FastAPI app - the composition root
│   ├── main.py             #   assembles the ASGI app (lifespan, error
│   │                       #   handlers, routers) + `run()` entry point
│   ├── lifespan.py         #   builds infra + services, wires infra -> modules
│   ├── health.py           #   GET /health (app-level, not module-owned)
│   └── errors.py           #   exception handlers, registered from main.py
│
├── modules/                 # uv workspace members - one package each.
│   │                        # Each has the same layout: a public entry
│   │                        # point at its root, internal/ for everything
│   │                        # supporting it - see architecture.md
│   ├── agent/src/agent/
│   │   ├── service.py      #   AgentService - the module's public entry point
│   │   ├── api/            #   POST /chat + POST /chat/stream: router.py + schemas.py
│   │   └── internal/       #   ports.py, graph.py (state, the LangGraph
│   │                       #   workflow, AgentError), prompts.py
│   ├── rag/src/rag/
│   │   ├── service.py      #   RAGService - the module's public entry point
│   │   ├── api/            #   POST /rag/documents, /documents/file, /search
│   │   └── internal/       #   ports.py (Embedder, VectorStore), errors.py (RagError)
│   └── tool/src/tool/       # local tool registry - no internal/ (see architecture.md)
│       ├── registry.py     #   ToolRegistry + RegisteredTool - the module's public entry point
│       ├── decorator.py    #   the @mcp_tool decorator mechanism
│       └── tools/          #   public: one file per local tool
│           ├── pdf.py      #     extract_pdf
│           └── markdown.py #     extract_markdown
│
├── infrastructure/          # Concrete adapters - the only place that
│   ├── database.py         # imports MongoDB/Redis/Qdrant/LLM SDKs directly
│   ├── redis.py
│   ├── qdrant.py
│   └── llm.py              # OllamaProvider + MistralProvider (generate +
│                           #   generate_stream; LLM_PROVIDER picks one), OllamaEmbedder
│
├── shared/                  # Cross-cutting types + logic used by 2+ packages
│   ├── types.py             # zero dependencies on modules/* or infrastructure/*
│   ├── text.py              # chunk_text (heading/paragraph/sentence-aware)
│   ├── documents.py         # extract_document_text (txt/pdf/docx)
│   ├── prompt_formatters.py # format_history/context/tools/tool_results
│   ├── tool_calls.py        # parse_tool_calls
│   └── logging.py           # configure_logging(), called once from app/main.py
│
├── tests/                   # Mirrors modules/
│   ├── agent/
│   ├── rag/
│   └── tool/
│
├── pyproject.toml           # uv workspace root
├── docker-compose.yml        # mongodb, redis, qdrant (local dev only)
└── .env.example
```

## Dependency direction

```
app
 └─ agent  (Retriever, ToolRegistry, LLMProvider, Memory ports)
     ├─ rag ─────────────┐
     ├─ tool ────────────┤
     └─ (LLMProvider, Memory implemented directly) ─ infrastructure
```

`agent` has four ports; two (`Retriever`, `ToolRegistry`) are implemented
by sibling modules that own retrieval/tools as their whole job, two
(`LLMProvider`, `Memory`) by `infrastructure` directly since there's no
natural intermediate module for "talk to an LLM" or "cache a session" -
see [`.claude/rules/architecture.md`](.claude/rules/architecture.md) for
why that's not the same as `agent` importing `infrastructure`.

- `app/lifespan.py` is the only file allowed to import across more than one
  of `modules/*` and `infrastructure/*` - it constructs adapters and
  injects them into module services once, at startup. `app/main.py` just
  wires that in and mounts each module's router (e.g. `agent.api.router`);
  it, `app/errors.py`, `app/health.py`, and each module's `api.py` import
  from at most one module, not across the boundary.
- `agent` and `rag` depend only on `typing.Protocol` ports they own
  (`agent/internal/ports.py`, `rag/internal/ports.py`) - never on a
  concrete MongoDB/Redis/Qdrant/LLM client. `tool` has no infrastructure
  dependency at all - its tools run entirely in-process.
- `infrastructure/*` implements those ports and imports nothing from
  `modules/*`.

Full rules and rationale: [`.claude/rules/architecture.md`](.claude/rules/architecture.md).

## How to run

```bash
ollama pull qwen3:8b          # once - chat model (~5.2GB), reliable tool-calling
ollama pull nomic-embed-text  # once - embedding model used by rag (~0.3GB)
uv sync                       # install the workspace (root + agent/rag/tool)
docker compose up             # start mongodb, redis, qdrant (+ their admin UIs)
uv run app                    # start the FastAPI server (http://localhost:8000)
```

Local admin UIs (dev convenience only, not app runtime dependencies):

| Service            | URL                              |
| ------------------ | --------------------------------- |
| Qdrant dashboard    | http://localhost:6333/dashboard  |
| Mongo Express       | http://localhost:8082             |
| Redis Commander     | http://localhost:8083             |

Copy `.env.example` to `.env` and adjust if needed (defaults assume a local
Ollama server on its default port). No local model/GPU at all? Set
`LLM_PROVIDER=mistralai` and `MISTRAL_API_KEY` instead - `mistral-small-latest`
(the default) is free-tier eligible, and nothing else about the app changes;
`uv run --env-file .env app` if you're not relying on your shell to export
`.env` already (`uv run` alone does not read it). `GET /health` always works.
`POST /rag/documents` (JSON text) and `POST /rag/documents/file` (multipart
txt/pdf/docx upload) index a document; `POST /rag/search` finds relevant
chunks; `POST /chat` runs the full agent workflow (retrieve, run tools,
answer) end to end against whatever's been indexed. `POST
/chat/stream` runs the identical workflow but streams the final answer
back as plain text as it's generated, instead of waiting for the whole
thing - see [`api-conventions.md`](.claude/rules/api-conventions.md) on
why that's a separate endpoint rather than a flag on `POST /chat`.

```bash
uv run pytest        # run the test suite
uv run ruff check .  # lint
uv run ruff format . # format
```

Set `LOG_LEVEL=DEBUG` to see everything (per-node LLM calls, tool calls,
Redis/Mongo/Qdrant round trips) - default is `INFO`. Every infrastructure
adapter and module service is built exactly once, in `app/lifespan.py`, and
reused for every request - `AgentService`'s constructor is where both
compiled forms of the LangGraph workflow get built (see
[`architecture.md`](.claude/rules/architecture.md#dependency-injection)),
and neither compiles again per chat call.

### Performance notes

The agent workflow makes at most 2 sequential LLM calls per turn
(`execute_tools` → `generate_answer`, with `retrieve_context` running in
parallel alongside `execute_tools` rather than as a third call) rather
than routing through a per-step supervisor or a dedicated planner call -
both were tried and dropped: the supervisor's routing was always
deterministic anyway (more than doubled latency for no behavioral
benefit), and the planner's one-sentence "plan" turned out to have
exactly one consumer (`execute_tools`'s own tool-call prompt) that already
skips itself on most turns - see below - so the planner call ran and was
silently discarded far more often than it was used. Both remaining nodes
now gate themselves with a cheap local heuristic instead of a shared
planning step deciding for them:
`execute_tools` skips its LLM call entirely when the input doesn't mention
any registered tool by name (`agent.internal.graph._mentions_a_tool`), and
`retrieve_context` skips retrieval entirely on pure smalltalk/
acknowledgements ("hi", "thanks!" - `agent.internal.graph._is_smalltalk`)
that carry no retrievable content. `OLLAMA_KEEP_ALIVE` (default `30m`,
`.env.example`) keeps the Ollama model loaded between chat turns instead
of Ollama's own 5-minute idle unload, so a normal back-and-forth
conversation doesn't repeatedly pay model-load cost.
Model choice matters a lot on constrained hardware: `qwen3:8b` (~5.2GB) is
the default for a reason - it was tried against `gpt-oss:20b` (~13GB) on
16-17GB unified memory and was dramatically slower, consistent with
`gpt-oss:20b`'s published ~17GB VRAM footprint at Q4_K_M leaving almost no
headroom. `OLLAMA_REASONING=false` (the `.env.example` default) turns off
qwen3's chain-of-thought for lower latency; unset it (or set `low`/`medium`/
`high`) to trade speed for more careful answers.

### Session concurrency & scaling

`AgentService`/`AgentGraph` hold no per-session state - every call gets a
fresh `AgentState`, and conversation history lives entirely in Redis
(`agent_session:{session_id}`), not in process memory. Different sessions
never contend with each other and the app is horizontally scalable as a
result: any instance behind a load balancer can serve any session, since
Redis is the single shared source of truth. Two things specific to a
*single* session:
- Concurrent requests on the *same* `session_id` (a double-send, two tabs,
  a client retry) are serialized through `memory.session_lock` -
  `RedisSessionStore`'s `SET NX`-based distributed lock (see
  `infrastructure/redis.py`) held across the full load -> run workflow ->
  save sequence in `AgentService.run`/`run_stream`. Without it, two
  concurrent requests could both read the same starting history and then
  both save, with whichever save lands last silently discarding the
  other's turn - verified live by firing two concurrent `POST /chat`
  requests at one `session_id` and confirming both turns land in the
  final Redis-stored history, not just one.
- Session checkpoints carry a 7-day TTL (`_SESSION_TTL_SECONDS`,
  `infrastructure/redis.py`), refreshed on every save, so an abandoned
  session eventually ages out of Redis instead of accumulating forever;
  an active conversation never expires mid-use.

The actual ceiling on *concurrent* sessions today is the LLM backend, not
this module: `LLM_PROVIDER=ollama` (default) means every session's calls
hit one local Ollama process, which serializes/queues compute-bound
requests regardless of how many sessions the API layer accepts at once;
`mistralai` scales better concurrently (hosted) but its free tier is
rate-limited, not unlimited. There's no request-level concurrency
limiting/backpressure in front of either today.

## Extending this scaffold

**New module** (a 4th sibling of `agent`/`rag`/`tool`):
1. `mkdir -p modules/<name>/src/<name>`, add its own `pyproject.toml`
   (copy `modules/rag/pyproject.toml` as a template).
2. Add it to the root `pyproject.toml`'s `dependencies` and
   `[tool.uv.sources]`.
3. Put its service class at the root (`<name>/service.py`), everything
   supporting it under `<name>/internal/` (ports, exceptions, ...) -
   implement port implementations in `infrastructure/` if they wrap an
   external system. Don't create an empty `api/` "just in case" - only add
   it in step 4, if it's actually needed.
4. If it needs an HTTP surface, add `<name>/api/router.py` (an
   `APIRouter`) + `<name>/api/schemas.py` (see
   `modules/agent/src/agent/api/`), add `fastapi` to its `pyproject.toml`
   dependencies, and mount it from `app/main.py` via
   `app.include_router(...)` - don't add its routes to `app/main.py`
   directly.
5. Update the dependency diagram in `.claude/rules/architecture.md`.

**New local tool:**
1. Add a file to `modules/tool/src/tool/tools/` with an
   `@mcp_tool`-decorated async function (see `tools/pdf.py`).
2. Import it from `tools/__init__.py`. Nothing else changes.

**External tool-server integration (not implemented today):**
`tool` dropped its external-MCP-server client/loader (and the `mcp` SDK
dependency that came with it) once the app's only real need turned out to
be local tools - see
[`.claude/rules/tool-conventions.md`](.claude/rules/tool-conventions.md#implementation-status).
Re-adding it means reintroducing that dependency and reconciling it with
`tool`'s own package name (chosen specifically because it no longer
collides with `import mcp`).

**New LLM provider:** `MistralProvider` (remote, via `ChatMistralAI`) is a
real second implementation next to `OllamaProvider` (local, via
`ChatOllama`) - `LLM_PROVIDER` in `.env` picks between them, proving the
`LLMProvider` port actually earns its keep rather than being speculative
(see "Avoiding over-engineering" in
[`architecture.md`](.claude/rules/architecture.md)). To add a third:
1. Add a class to `infrastructure/llm.py` implementing `generate(self,
   prompt: str, max_tokens: int | None = None) -> str` and `generate_stream(self,
   prompt: str) -> AsyncIterator[str]` (structurally satisfies
   `agent.internal.ports.LLMProvider` - no inheritance needed). LangChain
   has a chat model for most hosted providers (`langchain-openai`,
   `langchain-anthropic`, ...) - wrap its `ainvoke`/`astream` the way
   `OllamaProvider`/`MistralProvider` wrap theirs, rather than hand-rolling
   HTTP calls. If the model's LangChain integration builds its request
   options from its own pydantic fields (as both `ChatOllama` and
   `ChatMistralAI` do), set `max_tokens`/`num_predict` via
   `chat.model_copy(update={...})`, not `.bind()` - the latter passes the
   kwarg straight through to the underlying SDK client call instead,
   which typically rejects it.
2. Wire it into `_build_llm_provider()` in `app/lifespan.py`, extending the
   `LLM_PROVIDER` branch.

**New cross-cutting type:** add it to `shared/types.py` only once a second
module actually needs it (see `Chunk`/`ToolDefinition`/`ToolResult`/
`ChatMessage`/`SessionCheckpoint` for the pattern - each used by 2+ of
`agent`/`rag`/`tool`/`infrastructure`) - a type only one module uses
belongs in that module, not `shared`.

**New coding rule:**
Add it to the relevant file under `.claude/rules/`, or a new file imported
from `CLAUDE.md` via `@.claude/rules/<name>.md`.

**Distributed deployment (later, not now):**
This is a monolith on purpose - see `.claude/rules/architecture.md` on
avoiding over-engineering. If a module genuinely needs to scale
independently later, the port/adapter boundary already in place is what
makes that extraction tractable: the module's `Protocol` becomes an RPC/HTTP
client instead of an in-process call, and nothing on the agent side changes.
