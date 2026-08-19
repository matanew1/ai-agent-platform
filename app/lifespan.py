"""Startup/shutdown wiring - the composition root's actual construction
logic.

Builds ``infrastructure`` adapters and module services **once, per
process** - this function runs exactly once (FastAPI calls it once per
app lifetime, not per request) - and attaches them to ``app.state`` so
route handlers never construct a *module* service (``AgentService``,
``RAGService``, ...) themselves. Every infrastructure connection below
must never happen per chat call, only once here. See
``.claude/rules/architecture.md`` (dependency injection).

``ChatService`` is the one exception: it bakes in a specific agent's
system prompt, model options, and owner-scoped retriever at construction,
and agent definitions are created/edited at runtime, so there is no fixed
set to build here. What *is* built once, below, is
``app.state.chat_service_factory`` - ``chat.service.build_chat_service``
partially applied over the shared dependencies (``llm``, ``rag_service``,
``session_memory``, ``tool_registry``) - so ``chat.controller`` still
only ever reads one ``app.state`` attribute per the rule above; it
supplies just the per-turn ``agent`` argument the partial leaves open,
the same shape as calling any other constructed service, not wiring one
up itself.
``app/main.py`` only wires this in as the FastAPI app's ``lifespan``; it
doesn't build anything itself.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from functools import partial

from agent.draft_service import DraftService
from agent.repository import AgentRepository
from agent.service import AgentService
from artifact.repository import ArtifactRepository
from artifact.service import ArtifactService
from authentication.account_service import AccountService
from authentication.repository import AuthSettings, build_authenticator_from_env
from automation.repository import ScheduleRepository
from automation.runner import ScheduleRunner
from automation.service import ScheduleService
from chat.service import build_chat_service
from fastapi import FastAPI
from feedback.repository import FeedbackRepository
from feedback.service import FeedbackService
from rag.repository import RagRepository
from rag.service import RAGService
from session.repository import SessionRepository
from session.service import HybridSessionStore
from settings.repository import SettingsRepository
from settings.service import SettingsService
from tool.service import ToolService
from tool.tools.local import ats, markdown, pdf
from tool.tools.mcp.config import load_servers

from infrastructure.cache.redis import RedisCache
from infrastructure.database.postgres import PostgresDatabase
from infrastructure.llm.ollama import OllamaEmbedder, OllamaProvider
from infrastructure.vector_database.qdrant import QdrantVectorDatabase

logger = logging.getLogger(__name__)

_DEFAULT_TEMPERATURE = 0.3


def _parse_reasoning(raw: str | None) -> bool | str | None:
    """Parse ``OLLAMA_REASONING`` into what ``OllamaProvider`` expects.

    Unset -> ``None`` (leave the model's own default alone). ``"true"``/
    ``"false"`` -> a bool (fully on/off). Anything else (``"low"``,
    ``"medium"``, ``"high"``) is passed through as a reasoning-effort
    string - see ``infrastructure.llm.ollama``'s ``OllamaProvider`` docstring.
    """
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return lowered


def _parse_temperature(raw: str | None) -> float:
    """Parse the process-wide generation temperature shared by providers."""
    if raw is None:
        return _DEFAULT_TEMPERATURE
    try:
        temperature = float(raw)
    except ValueError as exc:
        raise RuntimeError("LLM_TEMPERATURE must be a number between 0 and 2.") from exc
    if not 0 <= temperature <= 2:
        raise RuntimeError("LLM_TEMPERATURE must be a number between 0 and 2.")
    return temperature


def _build_llm_provider() -> OllamaProvider:
    """Construct the local Ollama chat provider from the environment."""
    temperature = _parse_temperature(os.getenv("LLM_TEMPERATURE"))
    return OllamaProvider(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        temperature=temperature,
        reasoning=_parse_reasoning(os.getenv("OLLAMA_REASONING")),
        # Defaults to 30m (Ollama's own default is 5m) so a chat session
        # doesn't repeatedly pay model-load cost between turns - see
        # OllamaProvider's docstring. Override with OLLAMA_KEEP_ALIVE.
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        embedding_model=os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3"),
    )


def _build_embedder() -> OllamaEmbedder:
    """Construct the configured embedding provider."""
    return OllamaEmbedder(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Construct infrastructure adapters and module services once, at startup.

    Everything built here is attached to ``app.state`` so route handlers
    never construct services themselves.
    """
    logger.info("Lifespan startup: building infrastructure + module services (singleton)")

    # SECTION 1 - Build infrastructure adapters. Construction only: the
    # and the LLM provider connect lazily on first use, so there's nothing
    # to await for them yet.
    # Parsed twice (here and again inside build_authenticator_from_env) on
    # purpose rather than threading one result through: both calls are pure,
    # cheap env-var parsing, not I/O, and app.state needs the settings
    # object itself (cookie policy, redirect targets - see
    # authentication.controller) as well as the authenticator built from it.
    auth_settings = AuthSettings.from_environment()
    authenticator = build_authenticator_from_env()
    database = PostgresDatabase(
        os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform",
        )
    )
    redis_cache = RedisCache(redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    durable_sessions = SessionRepository(database.session_factory)
    artifact_service = ArtifactService(ArtifactRepository(database.session_factory))
    memory = HybridSessionStore(durable=durable_sessions, hot=redis_cache)
    vector_database = QdrantVectorDatabase(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
    )
    vector_store = RagRepository(vector_database)
    llm = _build_llm_provider()
    embedder = _build_embedder()

    # SECTION 2 - Open connections that need an explicit connect step.
    await database.connect()
    await redis_cache.connect()
    await memory.migrate_hot_checkpoints()
    logger.debug("PostgreSQL + cache connections opened")

    # From here on, everything through SECTION 6's yield runs inside this
    # try so that a failure in any of it (e.g. SECTION 3B's MCP server
    # failing to spawn) still releases the connections just opened above,
    # instead of leaking them while startup fails - see SECTION 7.
    mcp_exit_stack = AsyncExitStack()
    # Declared before the try so SECTION 7's finally can always check it,
    # even if startup fails before SECTION 4 ever creates the real task.
    schedule_runner_task: asyncio.Task[None] | None = None
    try:
        # SECTION 3 - Build the tool registry. Local tools are plain
        # functions (tool/tools/*.py) with no registration magic of their
        # own - each is registered explicitly, once, right here. The
        # generate/edit tools need `artifact_service` (to store what they
        # produce), bound here via `partial` since a tool handler is called
        # with only the LLM-supplied `arguments` dict - see
        # `tool.service.ToolService.call_tool`.
        tool_registry = (
            ToolService()
            .register_local(pdf.DEFINITION, pdf.extract_pdf)
            .register_local(
                pdf.GENERATE_DEFINITION,
                partial(pdf.generate_pdf, artifact_service=artifact_service),
            )
            .register_local(
                pdf.EDIT_DEFINITION, partial(pdf.edit_pdf, artifact_service=artifact_service)
            )
            .register_local(markdown.DEFINITION, markdown.extract_markdown)
            .register_local(
                markdown.GENERATE_DEFINITION,
                partial(markdown.generate_markdown, artifact_service=artifact_service),
            )
            .register_local(
                markdown.EDIT_DEFINITION,
                partial(markdown.edit_markdown, artifact_service=artifact_service),
            )
            .register_local(ats.DEFINITION, ats.analyze_ats_compatibility)
        )

        # SECTION 3B - Register every external MCP server declared in
        # tool/adapters/mcp/mcp-servers.yaml the same explicit way, just awaited
        # instead of a plain call - connecting is I/O a local tool doesn't
        # need. Adding a server is a new YAML entry, not a code change here.
        # mcp_exit_stack keeps every such connection open for the process's
        # lifetime and is closed in SECTION 7 alongside the other
        # connections opened in SECTION 2.
        for server_name, server_params in load_servers():
            # A subprocess an external MCP server spawns can fail in ways
            # load_servers() (a config-only check) can't see - the command
            # isn't installed, the process exits during the handshake, the
            # protocol negotiation fails. One server's runtime failure must
            # not take every other, correctly-starting server down with it,
            # the same "one bad entry doesn't cost the rest" guarantee
            # load_servers() already gives at the config layer - so this is
            # deliberately broad rather than a specific exception type.
            try:
                tool_registry = await tool_registry.register_mcp(
                    server_params, mcp_exit_stack, server_name
                )
            except Exception:
                logger.warning(
                    "Skipping MCP server %r: failed to start or connect",
                    server_name,
                    exc_info=True,
                )

        logger.debug("Tool registry ready: %s", [t.name for t in tool_registry.get_tools()])
        agent_service = AgentService(
            repository=AgentRepository(database.session_factory),
            tool_registry=tool_registry,
            model_catalog=llm,
        )
        draft_service = DraftService(
            agent_service=agent_service, tool_registry=tool_registry, model_catalog=llm
        )

        # SECTION 4 - Build module services, injecting the infrastructure and
        # registry built above through their constructors.
        rag_service = RAGService(vector_store=vector_store, embedder=embedder)
        settings_service = SettingsService(
            repository=SettingsRepository(database.session_factory), cache=redis_cache
        )
        feedback_service = FeedbackService(repository=FeedbackRepository(database.session_factory))
        # chat_service_factory is build_chat_service partially applied over
        # the shared dependencies it needs on every call - see this module's
        # docstring on why ChatService itself can't be built once, here,
        # like everything else in this section.
        chat_service_factory = partial(
            build_chat_service,
            llm=llm,
            retriever=rag_service,
            memory=memory,
            tool_registry=tool_registry,
        )
        schedule_service = ScheduleService(repository=ScheduleRepository(database.session_factory))
        account_service = AccountService(
            agent_service=agent_service,
            session_memory=memory,
            rag_service=rag_service,
            schedule_service=schedule_service,
        )
        logger.info("Module services ready")

        # SECTION 5 - Expose services to route handlers via app.state - see
        # .claude/rules/architecture.md (dependency injection).
        app.state.tool_registry = tool_registry
        app.state.authenticator = authenticator
        app.state.auth_settings = auth_settings
        app.state.artifact_service = artifact_service
        app.state.rag_service = rag_service
        app.state.session_memory = memory
        app.state.agent_service = agent_service
        app.state.draft_service = draft_service
        app.state.chat_service_factory = chat_service_factory
        app.state.model_catalog = llm
        app.state.settings_service = settings_service
        app.state.schedule_service = schedule_service
        app.state.account_service = account_service
        app.state.feedback_service = feedback_service

        # ScheduleRunner is the one background task in the whole app - it
        # reuses chat_service_factory/agent_service/redis_cache built above
        # rather than opening any connection of its own, the same "no new
        # infrastructure" property every other module service in this
        # section already has. Started here, not exposed on app.state:
        # nothing outside this function ever needs to reach it directly,
        # unlike schedule_service (which chat.controller-shaped routes call
        # into).
        schedule_runner = ScheduleRunner(
            schedules=schedule_service,
            agents=agent_service,
            chat_service_factory=chat_service_factory,
            cache=redis_cache,
        )
        schedule_runner_task = asyncio.create_task(schedule_runner.run_forever())

        # SECTION 6 - Hand control back to FastAPI; it serves requests until
        # shutdown, then execution falls through to teardown below.
        yield
    finally:
        # SECTION 7 - Release connections opened in SECTION 2 and SECTION 3B,
        # plus the background schedule runner started in SECTION 4.
        logger.info("Lifespan shutdown: releasing connections")
        if schedule_runner_task is not None:
            schedule_runner_task.cancel()
            with suppress(asyncio.CancelledError):
                await schedule_runner_task
        await mcp_exit_stack.aclose()
        await redis_cache.close()
        await database.close()
