"""FastAPI exception handlers for the generic, framework-facing error types.

Registered onto the app in ``app/main.py`` via ``app.add_exception_handler``
rather than the ``@app.exception_handler`` decorator, so this stays a
plain module with no import of the ``app`` instance itself - just handler
functions matching FastAPI's ``(Request, Exception) -> Response`` shape.
See ``.claude/rules/api-conventions.md``. Module-specific handlers (e.g.
``graph.graph.handle_agent_error`` for ``AgentError``) live beside the
exception type they handle instead of here.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from shared.types import PlatformError

logger = logging.getLogger(__name__)


async def handle_platform_error(request: Request, exc: PlatformError) -> JSONResponse:
    """Catch-all for every module/infrastructure failure without its own handler.

    FastAPI dispatches to the most specific handler registered for an
    exception's type, so this only fires for a ``PlatformError`` that has
    no bespoke handler of its own (e.g. ``graph.graph.AgentError`` has one) -
    typically an infrastructure failure (Redis/PostgreSQL/Qdrant/LLM down or
    unreachable) that a module already translated into its own exception
    type. Keep it generic (500, no status-code guessing per module) rather
    than growing a handler per infrastructure exception class.
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


__all__ = ["handle_not_implemented", "handle_platform_error"]
