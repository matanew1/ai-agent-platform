"""Background loop that fires due agent schedules.

The only genuinely new runtime behavior this feature adds: a plain
``asyncio`` polling loop, not a task-queue dependency - this repo has never
taken one (see ``.claude/rules/tool-conventions.md``'s "don't add an
abstraction you don't need yet" precedent, applied here to APScheduler/
Celery). Each fire replays exactly what ``chat.controller.stream_with_agent``
does minus the HTTP/streaming parts: build a ``ChatService`` via the same
``chat_service_factory`` the HTTP route uses, run one turn, and fully drain
its answer stream instead of forwarding it to a browser - draining is what
makes ``ChatService.run_stream`` persist the checkpoint and release its
per-session lock, see that method's own docstring in
``chat.service``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from agent.service import AgentService
from chat.service import ChatService

from automation.schemas import AgentSchedule
from automation.service import ScheduleService
from infrastructure.cache.protocol import Cache
from infrastructure.errors import CacheError

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "schedule_run:"


class ScheduleRunner:
    """Poll for due schedules and run one unattended agent turn for each."""

    def __init__(
        self,
        schedules: ScheduleService,
        agents: AgentService,
        chat_service_factory: Callable[..., ChatService],
        cache: Cache,
    ) -> None:
        self._schedules = schedules
        self._agents = agents
        self._chat_service_factory = chat_service_factory
        self._cache = cache

    async def run_forever(self, poll_interval_seconds: int = 30) -> None:
        """Poll for due schedules until the task is cancelled at shutdown."""
        while True:
            try:
                await self._fire_due()
            except Exception:
                # A single bad tick (a transient DB/cache error) must not
                # kill the loop for every future schedule - there's no
                # supervisor restarting this task, see app/lifespan.py.
                logger.exception("Schedule poll failed; retrying next interval")
            await asyncio.sleep(poll_interval_seconds)

    async def _fire_due(self) -> None:
        """Fire all due schedules."""
        now = datetime.now(UTC)
        for schedule in await self._schedules.due(now):
            await self._fire(schedule)

    async def _fire(self, schedule: AgentSchedule) -> None:
        """Run one turn for a single schedule, if its lock is available."""
        try:
            async with self._cache.lock(_LOCK_PREFIX + schedule.id):
                await self._run_once(schedule)
        except CacheError:
            # Another replica is already firing this schedule, or the cache
            # is briefly unavailable - skip this tick, it's due again next
            # poll since next_run_at only advances after a real run.
            logger.warning("Skipped schedule %s: lock unavailable", schedule.id)
        except Exception:
            # A single schedule's turn failing (a bad tool call, an LLM
            # error) must not stop the rest of this tick's due schedules
            # from firing - each is independent.
            logger.exception("Schedule %s failed to run", schedule.id)

    async def _run_once(self, schedule: AgentSchedule) -> None:
        """Run one turn for a single schedule, assuming its lock is held."""
        # 1. Load the agent for this schedule, skipping if it no longer exists.
        agent = await self._agents.get(schedule.owner_id, schedule.agent_id)
        if agent is None:
            logger.info("Skipped schedule %s: agent no longer exists", schedule.id)
            return

        # 2. Build a ChatService and run one turn, fully draining the stream.
        # A fresh session_id every fire is deliberate, not an oversight: each
        # scheduled run is an independent unattended trigger, not a resumed
        # conversation - record_run's last_run_session_id is bookkeeping for
        # "where did the last result go", not a continuation pointer. An
        # agent that should build on its own prior output would say so in
        # trigger_message itself.
        session_id = (
            f"{schedule.owner_id}:{schedule.agent_id}:scheduled-{schedule.id}-{uuid4().hex}"
        )
        chat_service = self._chat_service_factory(agent=agent)
        _, stream = await chat_service.run_stream(
            session_id=session_id, message=schedule.trigger_message, tools=agent.allowed_tools
        )

        # 3. Drain the stream to trigger the turn's checkpoint save and lock release.
        async for _ in stream:
            pass  # drain: triggers the turn's checkpoint save + lock release
        await self._schedules.record_run(schedule, session_id, ran_at=datetime.now(UTC))
        logger.info("Fired schedule %s for agent %s -> new session", schedule.id, schedule.agent_id)


__all__ = ["ScheduleRunner"]
