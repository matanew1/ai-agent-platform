"""Cached runtime construction for versioned user-owned agents."""

from __future__ import annotations

from agent.service import AgentService
from rag.service import RAGService

from shared.types import AgentDefinition, Chunk


class AgentScopedRetriever:
    """Restrict one runtime's retrieval to its owner's agent documents."""

    def __init__(self, retriever: RAGService, owner_id: str, agent_id: str) -> None:
        self._retriever = retriever
        self._metadata_filter = {"owner_id": owner_id, "agent_id": agent_id}

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Return only chunks indexed for this owner and agent."""
        return await self._retriever.search(query, top_k, metadata_filter=self._metadata_filter)


class AgentRuntimeFactory:
    """Build one compiled runtime per agent definition version."""

    def __init__(self, **dependencies: object) -> None:
        self._dependencies = dependencies
        self._runtimes: dict[tuple[str, int], AgentService] = {}

    def get(self, definition: AgentDefinition) -> AgentService:
        """Return the cached runtime matching a definition's current version."""
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
            if not isinstance(retriever, RAGService):
                raise TypeError("AgentRuntimeFactory requires a RAGService retriever.")
            runtime = AgentService(
                system_prompt=definition.system_prompt,
                retriever=AgentScopedRetriever(retriever, definition.owner_id, definition.id),
                **dependencies,
            )
            self._runtimes[key] = runtime
        return runtime
