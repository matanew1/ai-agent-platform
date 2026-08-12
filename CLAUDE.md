# ai-agent-platform

## Project Overview

A modular-monolith platform for building and running LLM agents. One deployable
service, internally split into isolated modules so agent logic, retrieval, and
tool access can evolve independently without becoming a distributed system
before there's a reason to be one.

**Purpose:** host conversational/task agents that reason over retrieved
context (RAG) and act through a local tool registry (`tool`, tool
definitions shaped like the Model Context Protocol's), with a clean seam
between business logic and the infrastructure that backs it.

**Stack**
- Python 3.12, [uv](https://docs.astral.sh/uv/) for dependency management and running
- FastAPI — HTTP boundary
- LangGraph — agent orchestration / state machines
- LangChain — LLM & tool abstractions (`ChatOllama`, `OllamaEmbeddings`)
- PostgreSQL — relational persistence (agents, sessions, artifacts)
- Redis — cache, short-lived state, agent session memory
- Qdrant — vector store for RAG
- Model Context Protocol (MCP) — external tool servers: `fetch`, `time`, `duckduckgo` (see `tool/adapters/mcp/`)

**Architecture:** see [architecture rules](.claude/rules/architecture.md) for
the full dependency-direction contract. In short:

```
app
 └─ agent      (LangGraph workflow + versioned agents + the public /agents HTTP surface, one module)
     └─ rag / tool
         └─ infrastructure
```

`infrastructure` never imports from `modules/*`. `agent` and `rag` never
import a database/cache/vector-store client, or a sibling module's
concrete class, directly — only through an interface (`Protocol`) each
owns in its own `ports.py`, implemented in `infrastructure`/`rag` and wired
together at the composition root (`app/lifespan.py`). Everything wired
there is a singleton for the process's lifetime - built once, never
per-request - with one deliberate exception: `chat.factory.AgentRuntimeFactory`
lazily compiles (and caches) one `ChatService` per agent
version on first use, since agents are created/edited at runtime and
there's no fixed set to pre-compile at startup. See
[architecture.md](.claude/rules/architecture.md#dependency-injection).

**Implementation status:** `agent`, `rag`, and `tool` are all fully
implemented, not scaffolding - a real LangGraph workflow
(`retrieve_context` -> `execute_tools` -> streamed `generate_answer`, with
retrieval feeding context-aware tool execution) calling a real LLM
(`ChatOllama`, including Ollama's hosted cloud models such as
`OLLAMA_MODEL=minimax-m3:cloud`), real retrieval/ingestion against a real Qdrant
collection, and a real
tool registry: local pdf/markdown extraction/generation/editing plus three
tools adapted from external MCP servers (`fetch`, `time`, `duckduckgo` -
see [tool-conventions.md](.claude/rules/tool-conventions.md), which also
documents two servers evaluated and deliberately left disabled, `sqlite`
and `git`, and the measured tool-selection-accuracy method behind both
calls). All of it is verified against live services, not just unit-tested.
`agent` persists versioned agents through `/agents`: each has an
independent prompt and tool allowlist, plus a Redis session namespace, with
a streaming chat route (`/agents/{agent_id}/chat/stream`, which also
accepts optional ephemeral file attachments folded into that turn's answer
only). Documents live in a separate, user-scoped library (`/documents`,
`/documents/file` - not nested under `/agents/{agent_id}`) shared by every
agent belonging to the authenticated user, rather than tied to one agent. CORS is
configurable via `APP_CORS_ORIGINS` (`app/main.py`). PostgreSQL is verified
at startup with a health query; schema changes are applied through Alembic.
WorkOS AuthKit bearer JWTs are verified
through cached JWKS; the verified `sub` is the only source of ownership, and
the app composition root also protects model-catalog and tool-registry access.
Direct `POST /tools/{name}` still bypasses the agent's own tool-call mediation,
which matters most for the filesystem tools
(`extract_pdf`/`extract_markdown`/`generate_pdf`/`edit_pdf`/
`generate_markdown`/`edit_markdown` - arbitrary local path, no sandboxing
today, and four of the six can write, not just read).

**History:** `agent` (private LangGraph workflow) and `agents` (public
`/agents` definitions + HTTP surface) were originally two workspace
members. They were merged into one `agent` module once the split stopped
earning its keep: `agents` had already become the app's only real agent
surface (nothing used a bare, unscoped `AgentService` any more - the
lifespan singleton that used to exist was dead weight, compiling a full
LangGraph workflow at every startup that no route ever read), and the
two-module boundary was actively encouraging the exact anti-pattern
`architecture.md` warns against elsewhere: `agents` importing `agent`'s,
`rag`'s, and `tool`'s concrete classes directly instead of through ports it
owned. One module removes both problems at once - what used to be a
cross-module port violation is now just an ordinary same-package import.

## Development Rules

- Inspect existing code before modifying it — match the patterns already in
  the file/module rather than introducing a new one.
- Prefer the smallest change that correctly solves the problem.
- Do not introduce a new abstraction (interface, base class, factory) for a
  single implementation "in case we need it later." Add it when the second
  concrete case actually shows up.
- Keep modules isolated: `modules/agent`, `modules/rag`, and `modules/tool`
  do not import each other's concrete classes — only canonical `Protocol`
  contracts from `infrastructure/`, and only when the dependency direction
  below allows it. All modules use the same semantic layers:
  `controller/`, `service/`, `repository/`, `dto/`, and `entity/` where
  needed. See
  [architecture.md](.claude/rules/architecture.md#module-internal-layout).
- New dependencies on **infrastructure resources** (databases, caches,
  vector stores, hosted LLM APIs) go through `infrastructure/`, never used
  ad hoc inside a module. This doesn't apply to a module's own core
  libraries - `tool` depending on `pypdf` is the module doing its actual
  job, not a bypass of the rule.

## Architecture Rules

**Allowed dependency direction**

```
app
 └─ agent
     └─ rag / tool
         └─ infrastructure
```

**Forbidden**

```
agent -> postgresql
agent -> redis
agent -> qdrant
rag   -> agent
tool  -> agent
infrastructure -> modules/*
```

Modules depend on infrastructure through interfaces they own (ports), not on
infrastructure's concrete clients. See
[architecture.md](.claude/rules/architecture.md) for the full rationale and
examples.

## Code Quality

- Type hints on every function signature and public attribute; no untyped
  `def`. Use built-in generics (`list[str]`, `dict[str, int]`), not
  `typing.List`/`typing.Dict`.
- Google-style docstrings on public functions, classes, and modules.
- `async def` for anything doing I/O (DB, HTTP, LLM calls, tool calls). Don't
  block the event loop with sync I/O.
- Meaningful, unabbreviated names — no `mgr`, `tmp2`, `data_obj`.
- `pytest` for all tests; see [testing.md](.claude/rules/testing.md).
- `logger = logging.getLogger(__name__)` in every file with real runtime
  logic (skip pure data/`Protocol` files). Configuration is centralized in
  `shared/logging.py`, called once from `app/main.py` — never call it
  elsewhere. Log lengths/counts/ids, never full prompt/response/user
  content. See [architecture.md](.claude/rules/architecture.md#logging).

## Detailed rules

@.claude/rules/architecture.md
@.claude/rules/python-style.md
@.claude/rules/testing.md
@.claude/rules/api-conventions.md
@.claude/rules/tool-conventions.md
