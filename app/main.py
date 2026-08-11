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
from agent.api.auth import get_current_user
from agent.api.router import documents_router, models_router
from agent.api.router import router as agents_router
from agent.graph import AgentError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from tool.api.router import router as tool_router

from app.errors import handle_agent_error, handle_not_implemented, handle_platform_error
from app.health import router as health_router
from app.lifespan import lifespan
from shared.artifacts import ARTIFACTS_URL_PATH, get_artifacts_directory
from shared.logging import configure_logging
from shared.types import PlatformError

# Before anything reads os.getenv - which is everything below, plus every
# default in app/lifespan.py. Without this, .env is inert: `uv run app`
# doesn't load it, so LLM_PROVIDER/OLLAMA_REASONING/MISTRAL_API_KEY/... all
# silently fell back to code defaults no matter what .env said. That was a
# real bug, not a theoretical one: OLLAMA_REASONING=false never applied, so
# qwen3 kept its default thinking mode on and consumed the whole
# _TOOL_CALL_MAX_TOKENS budget on reasoning tokens, making every tool call
# silently vanish (see infrastructure/llm.py's _require_content).
# override=False so a real exported env var still wins over the file.
load_dotenv(override=False)

# First thing that runs after the environment is loaded, before any other
# module logs anything - see shared/logging.py.
configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="ai-agent-platform", lifespan=lifespan)

# Comma-separated allowlist of origins allowed to call this API
# cross-origin - e.g. a frontend hosted on a different domain during local
# development (lovable.app, a dev server on another port, ...). Without
# this middleware, every browser request from such an origin fails with a
# CORS error before it ever reaches a route handler. "*" (the default)
# allows any origin; allow_credentials stays False to keep that default
# spec-compliant - browsers reject Access-Control-Allow-Credentials: true
# paired with a wildcard Access-Control-Allow-Origin. Set
# APP_CORS_ORIGINS to a real allowlist (and allow_credentials=True below,
# if needed) once this API is called with cookies/credentials.
_cors_origins = [
    origin.strip() for origin in os.getenv("APP_CORS_ORIGINS", "*").split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Tools-Invoked",
        "X-Chunks-Retrieved",
        "X-Prep-Time-Seconds",
        "X-Artifacts",
    ],
)

# Generated PDF/Markdown files are written only beneath ARTIFACTS_DIR by
# shared.artifacts and exposed read-only here. StaticFiles rejects methods
# other than GET/HEAD and prevents URL traversal outside this directory.
app.mount(
    ARTIFACTS_URL_PATH,
    StaticFiles(directory=get_artifacts_directory()),
    name="artifacts",
)

app.add_exception_handler(AgentError, handle_agent_error)
app.add_exception_handler(PlatformError, handle_platform_error)
app.add_exception_handler(NotImplementedError, handle_not_implemented)
app.include_router(health_router)
app.include_router(agents_router)
app.include_router(documents_router)
app.include_router(models_router, dependencies=[Depends(get_current_user)])
# Tools can perform network and filesystem work, so the composition root
# protects both registry reads and direct invocation without coupling the
# standalone ``tool`` module to the agent module's authentication dependency.
app.include_router(tool_router, dependencies=[Depends(get_current_user)])

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
