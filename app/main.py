"""FastAPI app assembly and process entry point.

Builds the ASGI app object - wires the lifespan (``app/lifespan.py``, which
builds ``infrastructure`` adapters and module services), registers
exception handlers (``app/errors.py``), and mounts each router - and
exposes ``run()``, the ``uv run app`` entry point that serves it with
uvicorn. This module, along with ``lifespan.py`` and ``errors.py``, is
where cross-module imports converge; see ``.claude/rules/architecture.md``.

    HTTP request -> module router -> AgentService -> (RAG, MCP tools) -> LLM -> response
"""

from __future__ import annotations

import logging
import os

import uvicorn
from agent.api.router import router as agent_router
from agent.internal.graph import AgentError
from fastapi import FastAPI
from rag.api.router import router as rag_router
from tool.api.router import router as tool_router

from app.errors import handle_agent_error, handle_not_implemented, handle_platform_error
from app.health import router as health_router
from app.lifespan import lifespan
from shared.logging import configure_logging
from shared.types import PlatformError

# First thing that runs, before any other module logs anything - see
# shared/logging.py.
configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="ai-agent-platform", lifespan=lifespan)
app.add_exception_handler(AgentError, handle_agent_error)
app.add_exception_handler(PlatformError, handle_platform_error)
app.add_exception_handler(NotImplementedError, handle_not_implemented)
app.include_router(health_router)
app.include_router(agent_router)
app.include_router(rag_router)
app.include_router(tool_router)

logger.debug("ASGI app assembled: %d route(s) registered", len(app.routes))


def run() -> None:
    """Entry point for ``uv run app`` - starts the server with uvicorn."""
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    logger.info("Starting uvicorn on %s:%s", host, port)
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=os.getenv("APP_RELOAD", "true").lower() == "true",
    )


if __name__ == "__main__":
    run()
