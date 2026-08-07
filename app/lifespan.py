"""Startup/shutdown wiring - the composition root's actual construction
logic.

Builds ``infrastructure`` adapters and module services **once, per
process** - this function runs exactly once (FastAPI calls it once per
app lifetime, not per request) - and attaches them to ``app.state`` so
route handlers never construct a service themselves. This is deliberate:
``AgentService.__init__`` constructs an ``AgentGraph`` and compiles it,
and that compile - along with every infrastructure connection below -
must never happen per chat call, only once here. See
``.claude/rules/architecture.md`` (dependency injection).
``app/main.py`` only wires this in as the FastAPI app's ``lifespan``; it
doesn't build anything itself.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from agent.service import AgentService
from fastapi import FastAPI
from rag.service import RAGService
from tool import tools  # noqa: F401 - import triggers @mcp_tool registration
from tool.decorator import register_local_tools
from tool.registry import ToolRegistry

from infrastructure.database import MongoDatabase
from infrastructure.llm import MistralProvider, OllamaEmbedder, OllamaProvider
from infrastructure.qdrant import QdrantVectorStore
from infrastructure.redis import RedisSessionStore

logger = logging.getLogger(__name__)


def _parse_reasoning(raw: str | None) -> bool | str | None:
    """Parse ``OLLAMA_REASONING`` into what ``OllamaProvider`` expects.

    Unset -> ``None`` (leave the model's own default alone). ``"true"``/
    ``"false"`` -> a bool (fully on/off). Anything else (``"low"``,
    ``"medium"``, ``"high"``) is passed through as a reasoning-effort
    string - see ``infrastructure/llm.py``'s ``OllamaProvider`` docstring.
    """
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return lowered


def _build_llm_provider() -> OllamaProvider | MistralProvider:
    """Construct the configured LLM provider from the environment.

    ``LLM_PROVIDER`` picks which one - ``"ollama"`` (default, local) or
    ``"mistralai"`` (remote, needs ``MISTRAL_API_KEY``). See
    ``infrastructure/llm.py`` for how to add a third provider without
    touching this function's call site below.

    Returns:
        Either concrete provider - both structurally satisfy
        ``agent.internal.ports.LLMProvider``.

    Raises:
        RuntimeError: ``LLM_PROVIDER`` is unrecognized, or is ``"mistralai"``
            with no ``MISTRAL_API_KEY`` set - fail at startup, not on the
            first chat request.
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider == "mistralai":
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=mistralai requires MISTRAL_API_KEY to be set.")
        return MistralProvider(
            api_key=api_key,
            model=os.getenv("MISTRAL_MODEL", "mistral-small-latest"),
        )
    if provider != "ollama":
        raise RuntimeError(f"Unknown LLM_PROVIDER {provider!r} - expected 'ollama' or 'mistralai'.")
    return OllamaProvider(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        reasoning=_parse_reasoning(os.getenv("OLLAMA_REASONING")),
        # Defaults to 30m (Ollama's own default is 5m) so a chat session
        # doesn't repeatedly pay model-load cost between turns - see
        # OllamaProvider's docstring. Override with OLLAMA_KEEP_ALIVE.
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
    )


def _build_embedder() -> OllamaEmbedder:
    """Construct the configured embedding provider."""
    return OllamaEmbedder(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Construct infrastructure adapters and module services once, at startup.

    Everything built here is attached to ``app.state`` so route handlers
    never construct services themselves.
    """
    logger.info("Lifespan startup: building infrastructure + module services (singleton)")

    # SECTION 1 - Build infrastructure adapters. Construction only: Qdrant
    # and the LLM provider connect lazily on first use, so there's nothing
    # to await for them yet.
    database = MongoDatabase(
        connection_uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        database_name=os.getenv("MONGODB_DATABASE", "ai_agent_platform"),
    )
    memory = RedisSessionStore(redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    vector_store = QdrantVectorStore(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
    )
    llm = _build_llm_provider()
    embedder = _build_embedder()

    # SECTION 2 - Open connections that need an explicit connect step.
    await database.connect()
    await memory.connect()
    logger.debug("Mongo + Redis connections opened")

    # SECTION 3 - Build the tool registry from local tools (tool.tools).
    tool_registry = ToolRegistry()
    register_local_tools(tool_registry)
    logger.debug("Tool registry ready: %s", [t.name for t in tool_registry.get_tools()])

    # SECTION 4 - Build module services, injecting the infrastructure and
    # registry built above through their constructors. AgentService.__init__
    # compiles the LangGraph workflow exactly once, right here - never
    # per-request (see module docstring).
    rag_service = RAGService(vector_store=vector_store, embedder=embedder)
    agent_service = AgentService(
        llm=llm,
        retriever=rag_service,
        memory=memory,
        tool_registry=tool_registry,
    )
    logger.info("AgentService + LangGraph workflow built once for this process")

    # SECTION 5 - Expose services to route handlers via app.state - see
    # .claude/rules/architecture.md (dependency injection).
    app.state.tool_registry = tool_registry
    app.state.rag_service = rag_service
    app.state.agent_service = agent_service

    # SECTION 6 - Hand control back to FastAPI; it serves requests until
    # shutdown, then execution falls through to teardown below.
    try:
        yield
    finally:
        # SECTION 7 - Release connections opened in SECTION 2.
        logger.info("Lifespan shutdown: releasing connections")
        await database.close()
        await memory.close()
