"""FastAPI exception handlers - the HTTP boundary's error mapping.

Registered onto the app in ``app/main.py`` via ``app.add_exception_handler``
rather than the ``@app.exception_handler`` decorator, so this stays a
plain module with no import of the ``app`` instance itself - just handler
functions matching FastAPI's ``(Request, Exception) -> Response`` shape.
See ``.claude/rules/api-conventions.md``.
"""

from __future__ import annotations

import logging

from agent.internal.graph import AgentError
from fastapi import Request
from fastapi.responses import JSONResponse

from shared.types import PlatformError

logger = logging.getLogger(__name__)


async def handle_agent_error(request: Request, exc: AgentError) -> JSONResponse:
    """Map agent-module failures to a consistent error response shape.

    No raw internal exception ever reaches the client - see
    ``.claude/rules/api-conventions.md``.
    """
    logger.warning("Agent workflow failed: %s", exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


async def handle_platform_error(request: Request, exc: PlatformError) -> JSONResponse:
    """Catch-all for every other module/infrastructure failure.

    FastAPI dispatches to the most specific handler registered for an
    exception's type, so this only fires for a ``PlatformError`` that isn't
    an ``AgentError`` - typically an infrastructure failure (Redis/Mongo/
    Qdrant/LLM down or unreachable) that a module already translated into
    its own exception type but that has no bespoke handler of its own. Keep
    it generic (500, no status-code guessing per module) rather than
    growing a handler per infrastructure exception class.
    """
    logger.error("Infrastructure failure: %s", exc, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


async def handle_not_implemented(request: Request, exc: NotImplementedError) -> JSONResponse:
    """Surface unimplemented scaffolding as 501 instead of a raw 500.

    This scaffold intentionally leaves business logic unimplemented (see
    the TODOs across ``modules/*`` and ``infrastructure/*``); this handler
    just makes that obvious over HTTP instead of a generic
    unhandled-exception 500. Remove once nothing in the request path can
    actually raise ``NotImplementedError`` anymore.
    """
    logger.debug("Unimplemented code path hit: %s", request.url.path)
    return JSONResponse(
        status_code=501,
        content={"detail": "Not implemented yet - see TODOs in the relevant module."},
    )
