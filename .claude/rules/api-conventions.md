# API Conventions (FastAPI)

## Structure

- Routers live per module, under its `api/` subfolder (see
  [architecture.md](architecture.md#module-internal-layout)):
  `modules/agents/src/agents/api/router.py` owns all public `/agents` routes,
  including definition CRUD, document ingestion, chat, and chat streaming.
  It is mounted from `app/main.py` via `app.include_router(agents_router)`.
  `modules/rag/src/rag/api/router.py` follows the same shape for
  `POST /rag/documents`, `POST /rag/documents/file`, and `POST /rag/search`.
  A router imports `fastapi` and module dependencies only - never `app`,
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

- Request and response models are Pydantic (v2) and live in `api/schemas.py`
  next to the router that uses them - e.g.
  `modules/agents/src/agents/api/schemas.py` holds public agent-definition
  and chat schemas. Keep them separate from the module's internal domain
  models (`agent.internal.graph.AgentState` is not the same type as
  `ChatRequest`) — don't expose an internal domain/DB model directly as an
  API response. `GET /health`'s `HealthResponse` is the one exception,
  defined in `app/health.py` alongside its route, for the same reason
  `/health` isn't in a module's `api/` pair.
- Name request/response models explicitly: `ChatRequest`/`ChatResponse`,
  not generic `Input`/`Output`.
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
  `agent.internal.graph`'s nodes do, means this handler won't even see it). Shape:

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
  RPC-style verbs in the path. Public conversations are nested under the
  resource they use: `POST /agents/{agent_id}/chat`.
- Streaming agent responses get their own clearly-named endpoint rather
  than a query-param flag that changes the response type of the normal
  endpoint - `POST /agents/{agent_id}/chat/stream` (`agents/api/router.py`)
  is the implemented example: same request schema as the normal agent chat,
  but a chunked
  `text/plain` `StreamingResponse` of the answer instead of waiting for
  the whole thing and returning JSON. It only streams the final answer -
  everything before it (planning, retrieval, tool calls) still has to
  finish first, same as normal agent chat - see
  `agent.service.AgentService.run_stream`. A nested resource path
  (`/agents/{agent_id}/chat/stream`),
  not a colon-suffixed custom-method style (`/chat:stream`, Google API
  design conventions) - the latter was tried first and reverted: it's
  valid HTTP, but every real client that hit it (including a plain `curl`
  test) instinctively tried the slash form and got a 404, which defeats
  the point of a "clearly-named" endpoint.
- Services are constructed once at the composition root
  (`app/lifespan.py`'s `lifespan`, see
  [architecture.md](architecture.md#dependency-injection)) and read from
  `request.app.state` in module routers today (see `agents/api/router.py`). Prefer
  `Depends(...)` for request-scoped things (e.g. an auth-derived user)
  if/when those show up - routes still never instantiate a service or
  infrastructure client themselves.
