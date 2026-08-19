"""Feedback submission: the module's public entry point."""

from __future__ import annotations

import logging

from feedback.repository import FeedbackRepository
from feedback.schemas import Feedback, FeedbackCategory

logger = logging.getLogger(__name__)


class FeedbackService:
    """Record a bug report or piece of product feedback for one owner."""

    def __init__(self, repository: FeedbackRepository) -> None:
        self._repository = repository

    async def submit(
        self,
        owner_id: str,
        category: FeedbackCategory,
        message: str,
        context_path: str | None = None,
    ) -> Feedback:
        """Persist one submission.

        Args:
            owner_id: The authenticated caller submitting the report.
            category: ``"bug"`` or ``"feedback"``.
            message: The submitter's free-text report - never logged (see
                ``.claude/rules/python-style.md``'s logging policy).
            context_path: The frontend route the submitter was on, for triage
                context only.

        Returns:
            The persisted submission.
        """
        submission = await self._repository.create(
            Feedback(
                owner_id=owner_id,
                category=category,
                message=message,
                context_path=context_path,
            )
        )
        logger.info(
            "Feedback submitted id=%r owner_id=%r category=%r message_chars=%d",
            submission.id,
            owner_id,
            category,
            len(message),
        )
        return submission
