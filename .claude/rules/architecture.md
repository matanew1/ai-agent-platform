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
                               Every module uses the same semantic layers when
                               that layer exists: controller/, service/,
                               repository/, dto/, and entity/.
    agent/src/agent/           — LangGraph workflow, agent configuration,
                                  persistence, and the public /agents API
        controller/             — HTTP routes and authentication
        service/                — turn service, definition service, runtime factory
        infrastructure/         — database/session/cache/auth/model adapters
        application/            — agent use cases and runtime construction
        dto/                    — request/response schemas
        domain/                 — graph, prompts, and repository contracts
    artifact/src/artifact/      — generated-file storage and ownership access
        domain/                 — safe filesystem storage and access contract
        infrastructure/         — PostgreSQL ownership persistence
    rag/src/rag/
        service/                — retrieval and ingestion service
        entity/                 — retrieval domain errors
        repository/             — vector-record to Chunk repository
    tool/src/tool/
        controller/             — HTTP routes
        dto/                    — request schemas
        registry/               — tool registry and execution orchestration
        entity/                 — local tool definitions and handlers
        adapters/mcp/            — external MCP connection/configuration

infrastructure/             — external capabilities and provider-neutral errors
    authentication/, cache/, database/, llm/, vector_database/
                             — capability-specific contracts and database lifecycle
    agent/, rag/, tool/      — module-facing business Protocols
    errors.py                — shared external-capability error hierarchy

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

**Implementation status:** `agent`, `rag`, and `tool` are all fully
implemented - real LangGraph nodes calling a real LLM, real retrieval/
ingestion against a real Qdrant collection, and a real local tool registry
(pdf/markdown extraction, generation, and editing) - none of it mocked in
tests. All three are additionally verified against live services, not just
unit-tested. `agent` owns all HTTP endpoints under `/agents` - it used to
be two modules (a private `agent` and a public `agents`) until the split
stopped earning its keep; see CLAUDE.md's "History" note.
`infrastructure.database`, `agent.infrastructure.cache`, and
`infrastructure.vector_database` provide the vendor-backed stores. They satisfy
focused Protocols in capability-specific infrastructure folders.

Each module owns its domain models and service layer. Canonical external-service
contracts and their concrete adapters live in the matching `infrastructure/`
capability folder. Infrastructure never imports from `modules/*`.

## Module-internal layout

Every workspace module uses the same semantic folders when a responsibility
exists: `controller/`, `service/`, `repository/`, `dto/`, and `entity/`.
Implementations live in their semantic folder, with no duplicate root copy.
Folders are not created empty: `agent` uses `controller/`, `service/`,
`repository/`, `dto/`, and `entity/`; `rag` uses
`service/`, `entity/`, and `repository/`; `tool` uses `controller/`,
`dto/`, `registry/`, `entity/`, and `adapters/mcp/` (MCP remains an integration adapter).

Layer meanings are consistent across modules:

- **`controller/`** contains HTTP routes and authentication boundary code.
- **`service/`** contains use-case services and orchestration.
- **`repository/`** contains persistence and external-capability translators owned by a module.
- **`dto/`** contains request/response data-transfer models.
- **`entity/`** contains policies, workflows, prompts, and local tool handlers.
- **`infrastructure/<capability>/protocol.py`** contains
  the canonical `Protocol` contracts. Modules implement them in their own
  `repository/`, `service/`, or `registry/` layers.

While consolidating, drop an exception subclass that nothing catches
specifically (`except SpecificError:`, not just `except AgentError:`) —
`PlanningError`/`ContextRetrievalError`/`ToolExecutionError` collapsed into
plain `AgentError` this way, and `rag`'s `EmbeddingError`/`VectorStoreError`
were removed outright (never even raised). `tool` has no exception type of
its own at all today - `ToolRegistry.call_tool` never raises (see
[tool-conventions.md](tool-conventions.md#boundary-discipline)), so there
was nothing to collapse.

When adding a new module, follow the same layer names and create only the
folders that contain real code; do not create empty layers speculatively.

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
  user data — see `agent/repository/language_model.py`'s `generate()` (`prompt_len=`,
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
- `infrastructure/agent/`, `infrastructure/rag/`, and `infrastructure/tool/` own the business ports for `Retriever`,
  `ToolRegistry`, `Memory`, and `AgentRepository`. The agent's
  `agent/infrastructure/postgres_agent_repository.py` and `agent/infrastructure/postgres_session_repository.py` implement agent-specific behavior
  against those ports. Concrete stores are created in the composition root
  and explicitly marked as Protocol implementations.
- `agent` repositories own PostgreSQL statements for their aggregates and consume
  `Cache` where appropriate. `rag` does the same with
  `VectorDatabase`, `LanguageModelClient`, and `EmbeddingClient`.
  Module repositories implement the business ports: `ArtifactRepository`,
  `AgentRepository`, `HybridSessionStore`, `VectorStoreRepository`,
  `OllamaProvider` and `OllamaEmbedder`.
- `tool` executes local handlers in-process (plus optional MCP adapters) and
  references only the canonical `ToolRegistry` contract.
- `infrastructure` depends on nothing in `modules/*`. It only knows about the
  external-service contracts and provider-neutral errors. Vendor implementations stay
  in the owning module.

**Forbidden:**

```
agent -> postgresql        # skip the owning repository, reach the SDK directly
agent -> redis
agent -> qdrant
rag   -> agent             # upward/circular dependency
tool  -> agent
infrastructure -> modules/*
```

The same rule applies to external stores: module repositories may import only
focused Protocols from capability-specific infrastructure folders; vendor SDKs are isolated
inside module-owned store implementations. Domain persistence stays in `agent`,
where its ownership and serialization rules can evolve with the service.

In the current codebase this is enforced structurally, not just by
convention: `agent.application`/`agent.domain` import only focused infrastructure contracts and
`shared.types`; `agent.infrastructure` additionally imports vendor SDKs — **zero** direct imports of `rag`,
`tool`, or infrastructure SDKs, even though the diagram above shows
`agent` "depending on" them. The concrete
`RAGService`/`ToolRegistry`/`OllamaProvider` instances are constructed in
`app/lifespan.py` and passed into `AgentService`'s constructor, which only
  knows them by their `Retriever`/`ToolRegistry`/`LanguageModelClient` shape.
`app/lifespan.py` is the only file that imports across more than one of
`agent`/`rag`/`tool`/`infrastructure` at once - every other file
under `app/` (`main.py`, `errors.py`, `health.py`) imports from at most one
of them (or none), so they don't count as composition-root code. If a new
file under `app/` ever needs to import across that boundary too, that's a
sign it belongs in `lifespan.py`, not a reason to add another
exception.

## Dependency inversion

Modules depend on **canonical infrastructure abstractions**, not on external
implementations:

```python
# infrastructure/rag/protocol.py
from typing import Protocol


class VectorStore(Protocol):
    async def search(self, embedding: list[float], top_k: int) -> list[Chunk]: ...


# infrastructure/rag/vector_store.py
class VectorStoreRepository:  # implements VectorStore structurally
    async def search(self, embedding: list[float], top_k: int) -> list[Chunk]: ...
```

`rag` imports `VectorStore` (the canonical infrastructure `Protocol`). Its
`VectorStoreRepository` owns the external-to-domain mapping, while
`infrastructure.vector_database.protocol.VectorDatabase` defines primitive
record operations; `infrastructure.vector_database.qdrant.QdrantVectorDatabase`
provides the vendor implementation.
Wiring both into the RAG service happens once at the composition root.

This isn't just illustrative - `rag`/`VectorStoreRepository` work exactly this
way in the running code, verified live through owner-scoped document ingestion
 and chat. The same pattern holds for the shared `LanguageModelClient`,
implemented by `OllamaProvider` in `infrastructure/llm/ollama.py`. It does
not import `agent`, and `agent.entity` never imports `infrastructure`.

Use `typing.Protocol` for ports by default (structural typing, no inheritance
coupling). Reach for an `abc.ABC` base only when you need shared
implementation, not just a shared shape.

Structural implementations are marked with `@implements(...)` from
`shared.implements`. The marker is semantic only: it records the intended
contract and deliberately performs no validation or inheritance. Infrastructure
clients and module repositories both reference the canonical contracts in
`infrastructure/`.

## SOLID, applied here

- **S**ingle responsibility — a service class does one thing (e.g.
  `ConversationService` doesn't also embed documents).
- **O**pen/closed — add a new vector store or LLM provider by writing a new
  module repository against the existing infrastructure client protocol, not
  by branching inside a service on a provider-name string.
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
  only place in the codebase that constructs external clients and module
  stores (`PostgresDatabase`, `RedisCache`, `QdrantVectorDatabase`,
  `OllamaProvider`, `OllamaEmbedder`) and injects them into services (`RAGService`,
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
  lifetime — constructed exactly once, reused for every request** - with
  one deliberate, documented exception: `AgentService`. `AgentService` is
  streaming-only (`run_stream()` - there is no non-streaming `run()`); its
  constructor builds an `AgentGraph` and compiles the retrieval/tool-
  execution preparation graph (`compile_prefix()` - there is no separate
  full-workflow `compile()` either, since the final answer is generated by
  `ChatService` itself, outside the graph, so it can be streamed - see
  `graph.graph.AgentGraph`'s docstring). Unlike every other service in
  `lifespan`, this compile does **not** happen eagerly at startup: agents
  are created and edited at runtime, so there is no fixed set
  to pre-compile up front. `chat.factory.AgentRuntimeFactory` (also built
  in `lifespan`, but itself cheap - it holds dependencies, not a compiled
  graph) lazily compiles and caches one `ChatService` per agent
  `(id, version)` the first time that agent is used, and reuses it
  until the agent's `version` changes. Nothing in the request path
  *constructs the factory* - `chat.controller` reads it from
  `request.app.state` - but the factory's own `get()` does construct a
  `ChatService` on a cache miss; that is the one place in this codebase
  where "construct on the request path" is correct, not a violation, and
  it logs `"ChatService runtime compiled: agent_id=... version=..."` at
  DEBUG when it happens so the lazy compile is observable, not just
  asserted.

## Avoiding over-engineering

- Don't add a port/interface for a dependency with exactly one implementation
  and no near-term second one — a concrete class is fine until a second
  implementation is real.
- Don't add a new module for a handful of functions — put them in the module
  that owns the concept until the boundary earns itself.
- Prefer composition over deep inheritance hierarchies everywhere in
  `modules/*`.
- Don't keep a capability "just in case" once it's unused - `tool` dropped
  its external-MCP-server client/loader (and the `mcp` SDK dependency that
  came with it) when the app's only real need turned out to be local tools;
  see [tool-conventions.md](tool-conventions.md#implementation-status) for
  what re-adding it later would involve.
