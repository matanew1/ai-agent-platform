"""FastAPI app assembly and process entry point.

Builds the ASGI app object - wires the lifespan (``app/lifespan.py``, which
builds ``infrastructure`` adapters and module services), registers each
exception handler (module-specific ones live beside their exception type,
e.g. ``graph.graph.handle_agent_error``; generic ones live in
``shared/errors.py``), and mounts each router - and exposes ``run()``, the
``uv run app`` entry point that serves it with uvicorn. This module, along
with ``lifespan.py``, is where cross-module imports converge; see
``.claude/rules/architecture.md``.

    HTTP request -> module router -> AgentService -> (RAG, MCP tools) -> LLM -> response
"""

from __future__ import annotations

import logging
import os

import uvicorn
from agent.controller import router as agents_router
from artifact.controller import router as artifacts_router
from authentication.controller import get_current_user
from authentication.controller import router as auth_router
from chat.controller import router as chat_router
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from graph.graph import AgentError, handle_agent_error
from model.controller import router as models_router
from rag.controller import router as documents_router
from tool.controller import router as tool_router

from app.health import router as health_router
from app.lifespan import lifespan
from shared.errors import handle_not_implemented, handle_platform_error
from shared.logging import configure_logging
from shared.types import PlatformError

# Before anything reads os.getenv - which is everything below, plus every
# default in app/lifespan.py. Without this, env files are inert: `uv run
# app` doesn't load them itself, so OLLAMA_REASONING and every other
# setting would silently fall back to code defaults no matter what a file
# said. That was a real bug, not a theoretical one: OLLAMA_REASONING=false
# never applied, so qwen3 kept its default thinking mode on and consumed
# the whole _TOOL_CALL_MAX_TOKENS budget on reasoning tokens, making every
# tool call silently vanish (see infrastructure.llm.ollama's
# _require_content). override=False everywhere below so a real exported
# env var always wins over any file.
#
# Which template loads is picked by APP_ENV - but that has to already be a
# real (shell/platform-exported) environment variable to make the choice,
# since it's normally *set inside* the file being chosen here; see
# AUTHENTICATION.md. .env.prod when a deploy has exported APP_ENV=
# production (the normal case: a hosting platform sets config vars
# directly, not via a committed file), .env.dev otherwise - both are
# tracked templates with placeholder secrets, safe to commit. A plain
# .env, if present, loads last as a local-only override layer (gitignored)
# for real secrets/one-off tweaks without editing a tracked file.
_env_file = ".env.prod" if os.getenv("APP_ENV", "").strip().lower() == "production" else ".env.dev"
load_dotenv(_env_file, override=False)
load_dotenv(override=False)

# First thing that runs after the environment is loaded, before any other
# module logs anything - see shared/logging.py.
configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="ai-agent-platform", lifespan=lifespan)

# Comma-separated allowlist of origins allowed to call this API
# cross-origin - e.g. a frontend hosted on a different domain during local
# development. Without this middleware, every browser request from such an
# origin fails with a CORS error before it ever reaches a route handler.
# allow_credentials=True because authentication.controller now issues a
# session *cookie* (see authentication/repository.py's cookie_policy) -
# every route that reads it depends on the browser being allowed to send
# credentialed cross-origin requests. That makes the allowlist load-bearing
# in a way it wasn't before: NEVER set APP_CORS_ORIGINS=* here again.
# Starlette's CORSMiddleware reflects the literal request Origin instead of
# a wildcard whenever allow_credentials=True (verified against its source),
# so "*" would let any website make cookie-authenticated requests on a
# signed-in user's behalf - there was no ambient credential to steal before,
# there is now.
_cors_origins = [
    origin.strip()
    for origin in os.getenv("APP_CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Tools-Invoked",
        "X-Chunks-Retrieved",
        "X-Prep-Time-Seconds",
        "X-Artifacts",
    ],
)

app.add_exception_handler(AgentError, handle_agent_error)
app.add_exception_handler(PlatformError, handle_platform_error)
app.add_exception_handler(NotImplementedError, handle_not_implemented)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(models_router, dependencies=[Depends(get_current_user)])
# Tools can perform network and filesystem work, so the composition root
# protects both registry reads and direct invocation without coupling the
# standalone ``tool`` module to the ``authentication`` module's dependency -
# same reasoning for ``models_router`` above.
app.include_router(tool_router, dependencies=[Depends(get_current_user)])
app.include_router(artifacts_router)

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
        # Without reload_dirs, uvicorn watches the whole project root -
        # including gitignored output dirs like artifacts/ and anything
        # else that gets written to at runtime - so unrelated file churn
        # (e.g. an artifact the agent just generated) triggers a reload
        # storm that has nothing to do with source changes. Scope
        # watching to the actual source trees: the composition root plus
        # each workspace member's src/.
        reload_dirs=[
            "app",
            "infrastructure",
            "shared",
            "modules/agent/src",
            "modules/rag/src",
            "modules/tool/src",
            "modules/artifact/src",
            "modules/authentication/src",
            "modules/model/src",
            "modules/chat/src",
            "modules/graph/src",
            "modules/session/src",
        ],
    )


if __name__ == "__main__":
    run()
