# API Conventions (FastAPI)

## Structure

- Routers live per module, under its `controller/` subfolder (see
  [architecture.md](architecture.md#module-internal-layout)):
  `modules/agent/src/agent/controller/router.py` defines three `APIRouter`s -
  `router` (`/agents`: definition CRUD and streaming chat) and
  `documents_router` (`/documents`: the authenticated user's document library,
  internally owner-scoped but not nested under `/agents/{agent_id}`), plus
  `models_router` (`/models`: provider configuration choices). They are mounted
  from `app/main.py` via
  `app.include_router(...)`. `rag` and `tool` expose no HTTP surface of
  their own besides `tool`'s own `/tools` routes - `rag` is consumed
  entirely through `agent`'s document routes. A public router imports
  `fastapi` and module dependencies only - never `app`,
  which would invert the one allowed direction (see
  [architecture.md](architecture.md)). It reaches services built at startup through the generic
  `request.app.state` FastAPI gives every handler, not through an import
  of the `app` package.
- `GET /health` is the one exception: it isn't module-specific, so it gets
  its own app-level router (`app/health.py`) instead of living in a
  business module - mounted the same way as `agents_router`.
- No `/api/v1` prefix yet - add real versioning if/when there's a reason to
  run two API versions concurrently, not preemptively.
- Routes are thin: parse/validate input, call one service method, map the
  result/exception to a response. No business logic belongs in `app/`.
- Route handlers are `async def`; they call into `async` service methods.

## Pydantic models

- Request and response models are Pydantic (v2) and live in `schemas.py`
  next to the router that uses them - e.g.
  `modules/agent/src/agent/schemas.py` holds public agent
  schemas, with chat-turn schemas in `chat.schemas`. Keep them separate
  from the module's internal domain models (`graph.state.AgentState` is
  not the same type as `ChatRequest`) — don't expose an internal domain/DB model directly as an
  API response. `GET /health`'s `HealthResponse` is the one exception,
  defined in `app/health.py` alongside its route, for the same reason
  `/health` isn't in a module's `controller/` pair.
- Name request models explicitly: `ChatRequest`, not generic `Input`.
- Use Pydantic validators for request-shape/field validation (`Field(...)`,
  `field_validator`). Cross-field or business-rule validation that needs
  repository/service access belongs in the service layer, not the schema.

## Validation & errors

- Let FastAPI/Pydantic handle shape validation (422 on bad input) —
  don't hand-roll it in the route.
- Business-rule failures raise the module's own exception types (see
  [python-style.md](python-style.md)); shared FastAPI exception handlers
  map them to HTTP responses. They live in `app/errors.py` (registered onto
  the app from `app/main.py` via `app.add_exception_handler(...)`, not the
  `@app.exception_handler` decorator, so `errors.py` stays a plain module
  that doesn't need to import the `app` instance). Current handlers, most
  to least specific (FastAPI dispatches to the closest match in the
  exception's MRO, so registration order doesn't matter):
  `handle_agent_error` maps `AgentError` → 502; `handle_platform_error`
  maps every other `PlatformError` (e.g. `RedisError`, `DatabaseError` -
  an infrastructure failure a module already translated but didn't get a
  bespoke handler for) → 500; `handle_not_implemented` maps
  `NotImplementedError` → 501 (a scaffolding convenience for `rag`'s
  remaining `TODO`-stubbed methods — remove once nothing in the request
  path can actually raise it anymore; note that a module catching
  `NotImplementedError` itself and re-raising its own exception, as
  `agent.graph`'s nodes do, means this handler won't even see it). Shape:

```python
@app.exception_handler(NotFoundError)
async def handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})
```

- Never let a raw infrastructure exception (pymongo, qdrant-client, etc.)
  escape to the client — it should already have been translated into a
  module-level exception before it reaches the API layer.
  `handle_platform_error` is the safety net for that translation, not a
  substitute for doing it (see `infrastructure/redis.py`'s
  `except Exception as exc: raise RedisError(...) from exc` for the
  pattern).
- Error response body shape is consistent across the API:
  `{"detail": "human-readable message"}` — extend with a `code` field if a
  client needs to branch on error type programmatically, not by parsing
  `detail`.

## Endpoint structure

- Resource-oriented paths once there's a resource to name (e.g. a future
  `POST /api/v1/conversations`, `GET /api/v1/conversations/{id}`), not
  RPC-style verbs in the path. Conversations are streaming-only and nested
  under their agent: `POST /agents/{agent_id}/chat/stream`.
- Streaming responses use a clearly-named endpoint rather than a query-param
  flag that changes the response type. The route returns a chunked
  `text/plain` `StreamingResponse`; retrieval and tool calls finish before
  the answer begins streaming - see `agent.service.AgentService.run_stream`.
  Browser-readable `X-Tools-Invoked`, `X-Chunks-Retrieved`,
  `X-Prep-Time-Seconds`, and `X-Artifacts` headers describe that preparation;
  generated artifact references are also persisted in session history.
  A nested resource path
  (`/agents/{agent_id}/chat/stream`),
  not a colon-suffixed custom-method style (`/chat:stream`, Google API
  design conventions) - the latter was tried first and reverted: it's
  valid HTTP, but every real client that hit it (including a plain `curl`
  test) instinctively tried the slash form and got a 404, which defeats
  the point of a "clearly-named" endpoint.
- Services are constructed once at the composition root
  (`app/lifespan.py`'s `lifespan`, see
  [architecture.md](architecture.md#dependency-injection)) and read from
  `request.app.state` in module routers today (see `agent/controller/router.py`). The
  verified caller is request-scoped via `CurrentUser`/`Depends(...)`; its JWT
  `sub` is the only input to ownership scopes. `app/main.py` applies the same
  dependency while mounting `/models` and `/tools`, keeping the standalone
  tool module decoupled from agent authentication. Routes still never
  instantiate a service or infrastructure client themselves.
