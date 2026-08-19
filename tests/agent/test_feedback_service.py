"""Unit tests for feedback.service.FeedbackService."""

from __future__ import annotations

from feedback.schemas import Feedback
from feedback.service import FeedbackService


class FakeRepository:
    def __init__(self) -> None:
        self.created: list[Feedback] = []

    async def create(self, submission: Feedback) -> Feedback:
        self.created.append(submission)
        return submission


async def test_submit_persists_and_returns_the_submission() -> None:
    repository = FakeRepository()
    service = FeedbackService(repository)

    result = await service.submit("owner-1", "bug", "Nothing happens when I click Export.")

    assert result.owner_id == "owner-1"
    assert result.category == "bug"
    assert result.message == "Nothing happens when I click Export."
    assert repository.created == [result]


async def test_submit_carries_the_optional_context_path_through() -> None:
    repository = FakeRepository()
    service = FeedbackService(repository)

    result = await service.submit("owner-1", "feedback", "Love the tool grouping!", "/tools")

    assert result.context_path == "/tools"
