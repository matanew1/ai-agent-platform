"""Cached runtime construction for versioned, owner-scoped agents.

Each agent definition gets its own ``AgentService`` - a different system
prompt and a retriever scoped to that owner's documents, both baked in at
construction time (``AgentGraph`` isn't parameterized per-call). Building
one is not free (it compiles the LangGraph workflow twice - see
``AgentService.__init__``), so ``AgentRuntimeFactory`` compiles a
definition's runtime once, lazily, on first use, and reuses it until the
definition's ``version`` changes. This is *not* the same "build once at
startup" guarantee the rest of ``app/lifespan.py`` gives every other
service: agent definitions are created and edited at runtime, so there is
no fixed set to pre-compile at process start. The cache below is what
keeps a steady-state deployment from paying the compile cost more than
once per definition version.
"""

from __future__ import annotations

import logging

from agent.ports import Retriever
from agent.service import AgentService
from shared.types import AgentDefinition, Chunk

logger = logging.getLogger(__name__)


class OwnerScopedRetriever:
    """Retrieval scoped to one owner's document library.

    Documents belong to an owner (a future userID), not to a specific
    agent - see ``agent.api.router``'s ``documents_router``. Every agent
    that owner_id owns shares the same pool, so this only needs owner_id,
    not an agent_id.
    """

    def __init__(self, retriever: Retriever, owner_id: str) -> None:
        self._retriever = retriever
        self._metadata_filter = {"owner_id": owner_id}

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Return only chunks indexed for this owner."""
        return await self._retriever.search(query, top_k, metadata_filter=self._metadata_filter)


class AgentRuntimeFactory:
    """Build one compiled runtime per agent-definition version."""

    def __init__(self, **dependencies: object) -> None:
        self._dependencies = dependencies
        self._runtimes: dict[tuple[str, int], AgentService] = {}

    def get(self, definition: AgentDefinition) -> AgentService:
        """Return the cached runtime matching a definition's current version.

        A cache miss evicts every other cached version of the same
        definition first (only the latest version is ever worth keeping),
        then builds and caches a fresh one.
        """
        key = (definition.id, definition.version)
        runtime = self._runtimes.get(key)
        if runtime is None:
            self._runtimes = {
                cached_key: cached_runtime
                for cached_key, cached_runtime in self._runtimes.items()
                if cached_key[0] != definition.id
            }
            dependencies = self._dependencies.copy()
            retriever = dependencies.pop("retriever")
            llm = dependencies.pop("llm")
            runtime = AgentService(
                system_prompt=definition.system_prompt,
                retriever=OwnerScopedRetriever(retriever, definition.owner_id),
                llm=llm.with_options(
                    model=definition.model,
                    temperature=definition.temperature,
                ),
                **dependencies,
            )
            self._runtimes[key] = runtime
            logger.debug(
                "AgentService runtime compiled: agent_id=%r version=%d",
                definition.id,
                definition.version,
            )
        return runtime
