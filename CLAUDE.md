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
- LangChain — LLM & tool abstractions
- MongoDB — document persistence
- Redis — cache, short-lived state, pub/sub
- Qdrant — vector store for RAG

**Architecture:** see [architecture rules](.claude/rules/architecture.md) for
the full dependency-direction contract. In short:

```
app  →  agent  →  rag / tool  →  infrastructure
```

`infrastructure` never imports from `modules/*`. `modules/agent` never imports
a database/cache/vector-store client directly — only through an interface
(`Protocol`) it defines itself in `agent/internal/ports.py`, implemented in
`infrastructure` and wired together at the composition root
(`app/lifespan.py`). Everything wired there is a singleton for the
process's lifetime - built once, never per-request; see
[architecture.md](.claude/rules/architecture.md#dependency-injection).

**Implementation status:** `agent`, `rag`, and `tool` are all fully
implemented - a real LangGraph workflow ([`retrieve_context`
|| `execute_tools`] -> `generate_answer`, the first two in parallel) calling
a real LLM, real retrieval/ingestion against a real Qdrant collection, and
a real local tool registry (pdf/markdown extraction, plus a `fetch` tool
adapted from the external Fetch MCP server - see
[tool-conventions.md](.claude/rules/tool-conventions.md)). All three are
verified against live services, not just unit-tested. The one remaining
scaffold is `infrastructure/database.py`'s CRUD methods
(`find_one`/`insert_one`/`update_one`, still `NotImplementedError`) -
nothing in the current request path calls them; `connect`/`close` are
real, as are `infrastructure/{redis,qdrant,llm}.py` in full.

## Development Rules

- Inspect existing code before modifying it — match the patterns already in
  the file/module rather than introducing a new one.
- Prefer the smallest change that correctly solves the problem.
- Do not introduce a new abstraction (interface, base class, factory) for a
  single implementation "in case we need it later." Add it when the second
  concrete case actually shows up.
- Keep modules isolated: `modules/agent`, `modules/rag`, and `modules/tool` do
  not import each other's internals — only their public interfaces, and only
  when the dependency direction below allows it. This is now a literal file
  boundary too: `agent`/`rag`'s `src/<name>/` root holds only its public
  entry point (`service.py`) plus `api/` if it has one; everything else
  lives under `internal/`, which nothing outside the module ever imports
  from. `tool` is the deliberate exception - it has no `internal/`; see
  [architecture.md](.claude/rules/architecture.md#module-internal-layout)
  for why.
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
agent -> mongodb
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
