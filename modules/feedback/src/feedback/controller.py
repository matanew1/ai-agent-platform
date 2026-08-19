"""HTTP route for submitting a bug report or piece of product feedback.

Write-only on purpose: there is no ``GET /feedback`` here. Nothing in the web
client (or this app generally) needs to read submissions back - they're
triaged directly in the database, the same "don't build a capability nothing
calls" precedent ``.claude/rules/tool-conventions.md`` documents for the
removed ``tool_overrides`` layer. Add a list/detail route only alongside a
real reader (e.g. an admin view).
"""

from __future__ import annotations

from authentication.controller import current_user
from fastapi import APIRouter, Request, status

from feedback.schemas import CreateFeedbackRequest, FeedbackResponse
from feedback.service import FeedbackService
from shared.auth import AuthenticatedUser

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
@current_user
async def submit_feedback(
    payload: CreateFeedbackRequest, request: Request, current_user: AuthenticatedUser
) -> FeedbackResponse:
    """Record a bug report or piece of feedback from the authenticated user."""
    feedback_service: FeedbackService = request.app.state.feedback_service
    submission = await feedback_service.submit(
        current_user.id, payload.category, payload.message, payload.context_path
    )
    return FeedbackResponse(id=submission.id, created_at=submission.created_at)
