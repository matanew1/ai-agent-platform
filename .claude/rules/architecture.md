# Architecture Rules

## Modular boundaries

```
app/                        — FastAPI app; the composition root
    main.py                  — assembles the ASGI app (loads .env,
                                 configures logging, wires lifespan,
                                 registers error handlers, mounts routers)
                                 and exposes `run()`, the `uv run app`
                                 process entry point. load_dotenv() runs
                                 first, before configure_logging() and
                                 before anything reads os.getenv - `uv run`
                                 does not read .env itself, so without it
                                 every value in .env is silently inert
    lifespan.py               — the actual construction logic: builds
                                 infrastructure adapters + module services
                                 exactly once per process (singleton — see
                                 "Dependency injection" below), attaches
                                 them to app.state
    health.py                 — GET /health, the one app-level (not
                                 module-owned) router
    errors.py                — exception handlers (AgentError -> 502,
                                 PlatformError -> 500, NotImplementedError
                                 -> 501), registered from main.py

modules/                    — uv workspace members, one installable package each.
                               Each follows the same internal layout — see
                               "Module-internal layout" below:
    agent/src/agent/
        service.py             — private/admin workflow implementation (AgentService)
        internal/               — ports.py; graph.py (state, the LangGraph
                                   workflow, AgentError); prompts.py (large
                                   enough - 3 templates - to earn its own file)
    agents/src/agents/
        service.py             — public versioned agent-definition service
        runtime.py             — per-definition compiled AgentService cache
        api/                    — HTTP surface: /agents definition, document,
                                   chat, and streaming routes
    rag/src/rag/
        service.py             — private retrieval implementation (RAGService)
        internal/               — ports.py (Embedder, VectorStore,
                                   LLMProvider); errors.py (RagError);
                                   prompts.py (RERANK_PROMPT_TEMPLATE);
                                   reranker.py (rerank_chunks - see
                                   "Reranking" below). Ingestion stays in
                                   service.py, thin enough (chunk -> embed
                                   -> upsert) that it never needed its own
                                   file; reranking earned one once its
                                   prompt-building/parsing/fallback logic
                                   was more than "a few lines"
    tool/src/tool/             — tool registry. No internal/ here (see
                                  "Module-internal layout" below) - registry.py
                                  is the one root file, tool sources split
                                  into two sibling packages, both wired into
                                  it the same explicit way (register_local /
                                  register_mcp, called from app/lifespan.py -
                                  no decorators, no import-time side effects):
        registry.py             — the module's one public entry point
                                   (ToolRegistry + RegisteredTool)
        tools/                  — in-process tools: one file per tool
                                   (pdf.py, markdown.py, ...), each just a
                                   module-level DEFINITION (ToolDefinition)
                                   + a plain async handler function - where
                                   a new local tool gets added
        mcp/                    — tools adapted from an external MCP server:
                                   mcp-servers.yaml (one entry per server -
                                   fetch is today's one example - parsed by
                                   config.py::load_servers() into
                                   StdioServerParameters, no Python needed
                                   to add a server); adapter.py
                                   (McpServerAdapter - stdio connection +
                                   adaptation, reusable across
                                   servers, doesn't change per server)

infrastructure/             — concrete adapters, one file per external system
    database.py              — MongoDB
    redis.py                 — cache, agent session memory
    qdrant.py                — vector store client
    llm.py                   — LLM provider clients (Ollama today; add
                                 others, e.g. a hosted API, the same way)

shared/                     — cross-cutting types + logic used by 2+ packages
    types.py                  — PlatformError, Chunk, ToolDefinition,
                                 ToolResult, ChatMessage, SessionCheckpoint
                                 (zero dependencies on modules/* or infrastructure/*)
    text.py                   — chunk_text (heading/paragraph/sentence-aware
                                 splitting), used by rag
    documents.py               — extract_document_text (txt/pdf/docx), used
                                 by rag's file-upload endpoint
    prompt_formatters.py        — format_history/context/tools/tool_results,
                                 used by agent's graph nodes
    tool_calls.py              — parse_tool_calls, used by agent's execute_tools
    logging.py                — configure_logging(), called once from
                                 app/main.py — see "Logging" below
```

**Implementation status:** private `agent`, public `agents`, `rag`, and `tool` are all fully
implemented - real LangGraph nodes calling a real LLM, real retrieval/
ingestion against a real Qdrant collection, and a real local tool registry
(pdf/markdown extraction) - none of it mocked in tests. All three are
additionally verified against live services, not just unit-tested.
The public `agents` module owns all HTTP endpoints; singular `agent` and
`rag` are private implementations used by that module and by private tests.
`infrastructure/database.py` provides the complete CRUD surface used by
agent-definition persistence and verifies MongoDB availability with a startup
ping. `infrastructure/{redis,qdrant,llm}.py` are likewise fully implemented.

**Reranking:** `RAGService.search` optionally reranks a wider
vector-search candidate set with an LLM before returning `top_k` -
`rag.internal.reranker.rerank_chunks`, prompted from
`rag.internal.prompts.RERANK_PROMPT_TEMPLATE`. Vector similarity alone is
a coarse signal (the query and passage embeddings are computed
independently, never seen together); an LLM reading both at once catches
cases a bi-encoder gets fooled by. Measured, not assumed: on three
adversarial queries built around lexical-decoy passages (a cancellation
*fee* policy that shares vocabulary with "how do I cancel my
subscription?" without answering it, and similarly for a VPN and a
camera-crash query), plain vector search picked the wrong top-1 result
2 times out of 3; reranking corrected both, landing 3/3, for ~0.8s of
added latency per search. That's a real, worthwhile trade - unlike the
`sqlite`/`git` servers in `tool-conventions.md`, which measured to no net
benefit - so it defaults on (`RAG_RERANK=true` in `app/lifespan.py`,
reusing the same `llm` instance already built for `AgentService` - no
second provider, no second config).

Two levers control it, at different scopes:
- `RAG_RERANK` (env var, default `true`) - whether the process wires an
  `llm` into `RAGService` at all. `false` means reranking is never even
  attempted, at zero latency cost, useful for a deployment where
  vector-search speed matters more than the accuracy this adds.
- `rerank` (a `RAGService.search` parameter, default
  `true`) - a per-call opt-out once the capability exists. Requesting
  `rerank=True` when the process has no `llm` configured never raises -
  it silently no-ops to plain vector-search order, the same
  fail-soft contract `tool.registry.ToolRegistry.call_tool` holds for
  tool execution.

`.env.example` should have a `RAG_RERANK` line alongside the LLM
provider settings it reuses - not added yet, see the file's own note if
this comment is still here when you're reading it.

Each module owns its own domain models, service layer, and the interfaces
(ports) it depends on. `infrastructure/*` provides concrete adapters that
implement those interfaces — it never defines business logic and never
imports from `modules/*`.

## Module-internal layout

Within `modules/<name>/src/<name>/`, only the module's public surface lives
at the root:

- **`service.py`** (or, for `tool`, `registry.py`) — the module's
  one supported entry point. This is the only file other modules/`app`
  import from directly.
- **`api/`** — present only on modules with an HTTP surface (today, just
  `agent`). `router.py` (an `APIRouter`) + `schemas.py` (its request/response
  Pydantic models), mounted from `app/main.py`.
- **`tools/`/`mcp/`** on `tool` are the other public subfolders — not
  "internal," because they're exactly where new tools get added (a local
  Python function, or an adapted MCP server), not an implementation detail
  to hide.
- **`internal/`** — everything else, on modules where a nontrivial amount
  of "everything else" actually exists (`agent`, `rag`, both of which own
  a `Protocol` port something else could someday swap the implementation
  behind). Nothing outside the module imports from `internal/` — not
  `app`, not a sibling module, not tests reaching past the module's public
  surface. `internal/__init__.py` says so explicitly; read it before adding
  an import that reaches into another module's `internal/`.
- **`tool` has no `internal/`** — `tools/`/`mcp/` sit at the module root
  next to `registry.py`. This is a deliberate exception, not a lapse:
  `internal/`'s job is hiding an implementation behind a `Protocol`
  boundary so it's free to change shape, but `tool` doesn't own a port of
  its own the way `agent`/`rag` do - it structurally satisfies a `Protocol`
  `agent` owns (`agent.internal.ports.ToolRegistry`), rather than defining
  one of its own to hide an implementation behind. The actual boundary that
  matters - `agent` never importing `tool.registry`, `tool.tools`, or
  `tool.mcp` directly - is already enforced by `agent` only depending on
  its own `ToolRegistry` `Protocol`, not by a directory hiding those files.
  Nesting them under `internal/` would add a path segment with no real
  protection behind it, on a module small enough that flat is still easier
  to navigate. If `tool` ever grows a second axis of "implementation
  detail vs. public surface" - e.g. it starts
  owning a `Protocol` of its own - revisit this.

Why: a module's `service.py`/`registry.py` signature is a promise to the
rest of the codebase; everything under `internal/` can be restructured
freely because nothing outside the module depends on its shape. This is
the same reasoning as `Protocol`-based ports (see "Dependency inversion"
below), one level up — the module's *file layout*, not just its runtime
interface, has a stable public part and a free-to-change private part.

`internal/` holds as few files as the module actually needs, not one file
per concept by default. `ports.py` stays separate everywhere it exists:
it's the module's dependency *contract*, not part of how the workflow is
implemented, and the two change for different reasons. Beyond that, `agent`
and `rag` have taken different shapes because their actual logic does:
`agent/internal/` is `ports.py` + `graph.py` (state, the LangGraph
workflow, `AgentError`) + `prompts.py` (three templates, big enough to earn
its own file once `graph.py` was mostly control flow without them).
`rag/internal/` is just `ports.py` + `errors.py` (`RagError`) -
`RAGService.ingest_document`/`search` themselves are a few lines of
chunk-embed-upsert/embed-search, thin enough that routing them through a
separate `internal/pipeline.py` would have been a layer of indirection
with nothing behind it; the logic lives directly in `service.py`. Neither
shape is "more correct" than the other - each reflects where that
module's actual complexity sits. `tool` has no `internal/` at all (see
above) - `registry.py` (`ToolRegistry`, `RegisteredTool`) is its one root
file, with `tools/` and `mcp/` split by where a tool comes from, not by
category: `tools/*.py` are plain functions with a `DEFINITION` constant,
registered via `ToolRegistry.register_local` (no I/O, so no need for
anything fancier); `mcp/adapter.py`'s `McpServerAdapter` handles the stdio
connection + adaptation for `ToolRegistry.register_mcp` (`async`, since
connecting *is* I/O) - two different registration mechanisms, not two
arbitrary halves of one file. Don't pre-split by category (one file each
for "exceptions", "state",
"config", ...) the way earlier passes over this codebase did, since
nothing outside the module sees those file boundaries anyway.

While consolidating, drop an exception subclass that nothing catches
specifically (`except SpecificError:`, not just `except AgentError:`) —
`PlanningError`/`ContextRetrievalError`/`ToolExecutionError` collapsed into
plain `AgentError` this way, and `rag`'s `EmbeddingError`/`VectorStoreError`
were removed outright (never even raised). `tool` has no exception type of
its own at all today - `ToolRegistry.call_tool` never raises (see
[tool-conventions.md](tool-conventions.md#boundary-discipline)), so there
was nothing to collapse.

When adding a new module: put its constructor/service class at the root,
everything supporting it under `internal/`, and only add `api/` if it
actually gets an HTTP surface — don't create an empty `api/` "just in
case" (see "Avoiding over-engineering" below).

## Logging

- Every file with real runtime logic gets `logger = logging.getLogger(__name__)`
  at module level — this is already "shared" behavior, it's the stdlib's
  global logger hierarchy. Pure data/`Protocol` files (`ports.py`,
  `state.py`, `schemas.py`, exception-hierarchy files) don't get one - an
  unused logger is dead code, not "coverage."
- What's actually centralized is the one-time *configuration* of that
  hierarchy - `shared/logging.py`'s `configure_logging()`, called exactly
  once from the top of `app/main.py`, before anything else runs. Never
  call it from a module, a route handler, or more than once.
- Log lengths/counts/ids, not full content, for anything that could carry
  user data — see `infrastructure/llm.py`'s `generate()` (`prompt_len=`,
  `response_len=`, never the prompt/response text itself).
- Level discipline: `debug` for per-call detail (what a node/adapter did,
  with values), `info` for lifecycle events (service constructed, request
  started/finished, tool registered), `warning` for handled-but-notable
  failures (a tool call failed), `error` for things the `PlatformError`
  catch-all handler surfaces as a 500. Set `LOG_LEVEL=DEBUG` locally to see
  everything; default is `INFO`.

## Dependency direction

```
app  →  agent  →  rag / tool / llm+memory  →  infrastructure
```

- `app` (FastAPI routers/entrypoint) depends on `agent`.
- `agent` has four ports (`agent/internal/ports.py`): `Retriever` and `ToolRegistry`
  are implemented by sibling modules (`rag`, `tool`) that own
  retrieval/tool-execution as their whole job; `LLMProvider` and `Memory`
  are implemented directly by `infrastructure` (`llm.py`, `redis.py`) since
  there's no natural intermediate module for "talk to an LLM" or "cache a
  session" the way there is for retrieval or tools. Both are still ports
  `agent` owns and depends on structurally - it never imports
  `infrastructure` itself either way (see below).
- `rag` depends on `infrastructure` through interfaces it defines
  (`VectorStore`, satisfied by `QdrantVectorStore`; `Embedder`, satisfied
  by `OllamaEmbedder` - both in `infrastructure/{qdrant,llm}.py`). `tool`
  has no infrastructure dependency at all today -
  its tools (`pypdf`, a regex stripper) run entirely in-process.
- `infrastructure` depends on nothing in `modules/*`. It only knows about the
  external systems it wraps (Mongo driver, Redis client, Qdrant client, LLM
  SDKs) and the interface contracts it must satisfy.

**Forbidden:**

```
agent -> mongodb          # skip rag/tool, reach infrastructure directly
agent -> redis
agent -> qdrant
rag   -> agent             # upward/circular dependency
tool  -> agent
infrastructure -> modules/*
```

"Skip rag/tool, reach infrastructure directly" doesn't apply to `LLMProvider`
and `Memory` above - `agent` importing `infrastructure.redis` directly
*would* still be forbidden (it only ever sees `RedisSessionStore` through
its own `Memory` `Protocol`), but there's no `rag`/`tool`-style
intermediate module to route through for those two, and inventing one
(e.g. a `modules/llm/`) just to satisfy the diagram would be exactly the
over-engineering this file argues against elsewhere.

In the current codebase this is enforced structurally, not just by
convention: `agent.service`/`agent.internal.graph` import only
`agent.internal.ports` (their own `Protocol`s) and `shared.types` —
**zero** direct imports of `rag`,
`tool`, or `infrastructure`, even though the diagram above shows
`agent` "depending on" them. The concrete
`RAGService`/`ToolRegistry`/`OllamaProvider` instances are constructed in
`app/lifespan.py` and passed into `AgentService`'s constructor, which only
knows them by their `Retriever`/`ToolRegistry`/`LLMProvider` shape.
`app/lifespan.py` is the only file that imports across more than one of
`agent`/`rag`/`tool`/`infrastructure` at once - every other file
under `app/` (`main.py`, `errors.py`, `health.py`) imports from at most one
of them (or none), so they don't count as composition-root code. If a new
file under `app/` ever needs to import across that boundary too, that's a
sign it belongs in `lifespan.py`, not a reason to add another
exception.

## Dependency inversion

Modules depend on **abstractions they own**, not on infrastructure
implementations:

```python
# modules/rag/internal/ports.py
from typing import Protocol


class VectorStore(Protocol):
    async def search(self, embedding: list[float], top_k: int) -> list[Chunk]: ...


# infrastructure/qdrant.py
class QdrantVectorStore:  # implements VectorStore structurally
    async def search(self, embedding: list[float], top_k: int) -> list[Chunk]: ...
```

`modules/rag` imports `VectorStore` (its own `Protocol`). `infrastructure`
imports nothing from `modules/rag` except the protocol it's implementing.
Wiring the concrete `QdrantVectorStore` into the `VectorStore`-shaped slot
happens once, at the composition root (FastAPI app startup / DI container) —
not inside the module that consumes it.

This isn't just illustrative - `rag`/`QdrantVectorStore` work exactly this
way in the running code, verified live through agent-scoped document ingestion
and chat. The same pattern holds for `agent.internal.ports.LLMProvider`,
now with two real implementations in `infrastructure/llm.py` -
`OllamaProvider` (local) and `MistralProvider` (remote, via
`ChatMistralAI`) - selected by `LLM_PROVIDER` in `app/lifespan.py`. Neither
imports `agent`, `agent.internal.graph` never imports `infrastructure`,
and both work end to end verified live: a real Ollama server and the real
Mistral API each answered the same agent workflow request correctly, with
`agent.internal.graph` unchanged either way.

Use `typing.Protocol` for ports by default (structural typing, no inheritance
coupling). Reach for an `abc.ABC` base only when you need shared
implementation, not just a shared shape.

## SOLID, applied here

- **S**ingle responsibility — a service class does one thing (e.g.
  `ConversationService` doesn't also embed documents).
- **O**pen/closed — add a new vector store or LLM provider by writing a new
  `infrastructure` adapter against the existing port, not by branching inside
  the module on a provider-name string.
- **L**iskov — any implementation of a port must be substitutable without the
  caller changing behavior; don't add provider-specific special cases at the
  call site.
- **I**nterface segregation — keep ports narrow (`VectorStore.search`, not a
  god `Database` interface with 20 methods only some callers need).
- **D**ependency inversion — see above: high-level modules (`agent`) depend on
  abstractions, low-level modules (`infrastructure`) implement them.

## Dependency injection

- Constructor injection only. No service locators, no module-level globals
  holding live clients.
- The composition root is `app/lifespan.py`'s `lifespan` context manager
  (wired into the `FastAPI(...)` instance from `app/main.py`): it's the
  only place in the codebase that constructs `infrastructure` adapters
  (`MongoDatabase`, `RedisSessionStore`, `QdrantVectorStore`,
  `OllamaProvider`) and injects them into module services (`RAGService`,
  `AgentService`, ...) via their constructors. The result is attached to
  `app.state` (e.g. `app.state.agent_runtime_factory`) and route handlers read it
  from `request.app.state` — routes never construct a service themselves.
  There is no separate `app/container.py`; introduce one only if `lifespan`
  actually gets unwieldy, not preemptively.
- Tests inject fakes/mocks that satisfy the same `Protocol` — never partially
  mock a concrete infrastructure class. See the fakes in `tests/agent/` for
  the pattern, including a `FakeLLMProvider` that varies its response by
  prompt content to exercise the graph's tool-calling branch without a real
  LLM.
- **Everything built in `lifespan` is a singleton for the process's
  lifetime — constructed exactly once, reused for every request.** This
  matters most for `AgentService`: its constructor builds an `AgentGraph`
  and **compiles** it twice - once as the full workflow (`compile()`, used
  by `run()`) and once as everything up to `generate_answer`
  (`compile_prefix()`, used by `run_stream()` for public agent streaming - see
  `agent.internal.graph.AgentGraph`'s docstring for why streaming needs a
  second compiled form rather than a flag on the first). Neither compile
  must ever happen per chat call, only once at startup. Nothing in the
  request path (`agents.api.router`, `AgentService.run`/`run_stream`)
  constructs anything; the router reads the configured runtime factory from
  `request.app.state`. Verified, not just asserted: booting
  the app with `LOG_LEVEL=DEBUG` shows `"AgentService + LangGraph workflow
  built once for this process"` exactly once at startup, and it does not
  appear again when an agent chat or streaming request is
  handled afterward.

## Avoiding over-engineering

- Don't add a port/interface for a dependency with exactly one implementation
  and no near-term second one — a concrete class is fine until a second
  implementation is real. `agent.internal.ports.LLMProvider` is the
  proof this isn't just theory: `infrastructure/llm.py` has two real
  implementations behind it (`OllamaProvider`, local; `MistralProvider`,
  remote), picked at startup by `LLM_PROVIDER` in `app/lifespan.py`, and
  `agent.internal.graph` didn't change one line to support the second one -
  it only ever depended on the `Protocol` shape.
- Don't add a new module for a handful of functions — put them in the module
  that owns the concept until the boundary earns itself.
- Prefer composition over deep inheritance hierarchies everywhere in
  `modules/*`.
- Don't keep a capability "just in case" once it's unused - `tool` dropped
  its external-MCP-server client/loader (and the `mcp` SDK dependency that
  came with it) when the app's only real need turned out to be local tools;
  see [tool-conventions.md](tool-conventions.md#implementation-status) for
  what re-adding it later would involve.
