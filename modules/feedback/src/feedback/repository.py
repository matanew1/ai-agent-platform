"""PostgreSQL persistence for feedback submissions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from feedback.models import FeedbackRecord
from feedback.schemas import Feedback


class FeedbackRepository:
    """Persist owner-scoped feedback submissions in PostgreSQL.

    No ``Protocol`` port: this is the only implementation - see
    ``.claude/rules/architecture.md``'s "Avoiding over-engineering". Create-only:
    there is deliberately no ``list``/``get`` here yet - nothing in this app reads
    submissions back (see ``feedback.controller``'s docstring on why).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, submission: Feedback) -> Feedback:
        async with self._session_factory() as session:
            session.add(FeedbackRecord(**submission.model_dump()))
            await session.commit()
        return submission
