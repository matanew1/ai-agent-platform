"""Delete every resource an authenticated user owns, across every module.

Composition-level orchestration, not a module-to-module dependency: this
service is built once in ``app/lifespan.py`` from already-constructed module
services (``agent``, ``session``, ``rag``, ``automation``) - the same way
``chat.service`` composes multiple modules' services without those modules
importing each other directly. Deliberately does not touch the identity
itself (the WorkOS account, the session cookie) - see
``authentication.controller``'s ``delete_account`` route for that half.
"""

from __future__ import annotations

import logging

from agent.service import AgentService
from automation.service import ScheduleService
from rag.service import RAGService
from session.service import HybridSessionStore

logger = logging.getLogger(__name__)


class AccountService:
    """Delete every agent (and its sessions/schedules) and document one owner has."""

    def __init__(
        self,
        agent_service: AgentService,
        session_memory: HybridSessionStore,
        rag_service: RAGService,
        schedule_service: ScheduleService,
    ) -> None:
        self._agent_service = agent_service
        self._session_memory = session_memory
        self._rag_service = rag_service
        self._schedule_service = schedule_service

    async def delete_all_owned_data(self, owner_id: str) -> None:
        """Delete every agent, session, schedule, and document owned by ``owner_id``.

        Agents own their sessions and schedules, so each agent's sessions/schedules
        are deleted before the agent itself; documents are owner-scoped independently
        of any agent (see ``.claude/rules/architecture.md`` on the document library
        being shared across an owner's agents, not nested under one), so they're
        deleted once at the end by owner id alone.

        Args:
            owner_id: The authenticated caller whose data is being erased.
        """
        agents = await self._agent_service.list(owner_id)
        deleted_agents = 0
        deleted_sessions = 0
        deleted_schedules = 0
        for agent in agents:
            scoped_prefix = f"{owner_id}:{agent.id}:"
            for checkpoint in await self._session_memory.list_checkpoints(scoped_prefix):
                await self._session_memory.delete_checkpoint(checkpoint.session_id)
                deleted_sessions += 1
            for schedule in await self._schedule_service.list_for_agent(owner_id, agent.id):
                await self._schedule_service.delete(owner_id, schedule.id)
                deleted_schedules += 1
            if await self._agent_service.delete(owner_id, agent.id):
                deleted_agents += 1
        await self._rag_service.delete_document({"owner_id": owner_id})
        logger.info(
            "Deleted account data owner_id=%r agents=%d sessions=%d schedules=%d",
            owner_id,
            deleted_agents,
            deleted_sessions,
            deleted_schedules,
        )
