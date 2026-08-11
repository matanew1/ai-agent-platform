"""Cached runtime construction for versioned, owner-scoped agents.

Each ``Agent`` gets its own ``ChatService`` - a different system prompt and
a retriever scoped to that owner's documents, both baked in at
construction time (``AgentGraph`` isn't parameterized per-call). Building
one isn't free (it compiles the LangGraph workflow - see
``ChatService.__init__``), so ``AgentRuntimeFactory`` compiles an agent's
runtime once, lazily, on first use, and reuses it until the agent's
``version`` changes. This is *not* the same "build once at startup"
guarantee the rest of ``app/lifespan.py`` gives every other service:
agents are created and edited at runtime, so there is no fixed set to
pre-compile at process start. The cache below is what keeps a
steady-state deployment from paying the compile cost more than once per
agent version.
"""

from __future__ import annotations

import logging

from chat.service import ChatService
from graph.graph import OwnerScopedRetriever

from shared.types import Agent

logger = logging.getLogger(__name__)


class AgentRuntimeFactory:
    """Build one compiled runtime per agent version."""

    def __init__(self, **dependencies: object) -> None:
        self._dependencies = dependencies
        self._runtimes: dict[tuple[str, int], ChatService] = {}

    def get(self, agent: Agent) -> ChatService:
        """Return the cached runtime matching an agent's current version.

        A cache miss evicts every other cached version of the same
        agent first (only the latest version is ever worth keeping),
        then builds and caches a fresh one.
        """
        key = (agent.id, agent.version)
        runtime = self._runtimes.get(key)
        if runtime is None:
            self._runtimes = {
                cached_key: cached_runtime
                for cached_key, cached_runtime in self._runtimes.items()
                if cached_key[0] != agent.id
            }
            dependencies = self._dependencies.copy()
            retriever = dependencies.pop("retriever")
            llm = dependencies.pop("llm")
            runtime = ChatService(
                system_prompt=agent.system_prompt,
                retriever=OwnerScopedRetriever(retriever, agent.owner_id),
                llm=llm.with_options(
                    model=agent.model,
                    temperature=agent.temperature,
                ),
                **dependencies,
            )
            self._runtimes[key] = runtime
            logger.debug(
                "ChatService runtime compiled: agent_id=%r version=%d",
                agent.id,
                agent.version,
            )
        return runtime


__all__ = ["AgentRuntimeFactory"]
