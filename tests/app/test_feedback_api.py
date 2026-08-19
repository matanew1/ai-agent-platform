"""Route-level tests for POST /feedback.

Same fake-authenticator shape as tests/app/test_agents_api.py's _Authenticator.
"""

from __future__ import annotations

from authentication.repository import SESSION_COOKIE_NAME, SessionResult
from fastapi import FastAPI
from fastapi.testclient import TestClient
from feedback.controller import router
from feedback.schemas import Feedback, FeedbackCategory

from shared.auth import AuthenticatedUser, AuthenticationError


class _Authenticator:
    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        if sealed_session is None:
            raise AuthenticationError("No session cookie was provided.")
        return SessionResult(
            user=AuthenticatedUser(id=sealed_session), sealed_session=sealed_session
        )


class _FeedbackService:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, FeedbackCategory, str, str | None]] = []

    async def submit(
        self,
        owner_id: str,
        category: FeedbackCategory,
        message: str,
        context_path: str | None = None,
    ) -> Feedback:
        self.submissions.append((owner_id, category, message, context_path))
        return Feedback(
            owner_id=owner_id, category=category, message=message, context_path=context_path
        )


def _client() -> tuple[TestClient, _FeedbackService]:
    app = FastAPI()
    feedback_service = _FeedbackService()
    app.state.authenticator = _Authenticator()
    app.state.feedback_service = feedback_service
    app.include_router(router)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: "owner-1"}), feedback_service


def test_submit_feedback_requires_a_session_cookie() -> None:
    client, feedback_service = _client()
    client.cookies.clear()

    response = client.post("/feedback", json={"category": "bug", "message": "It broke."})

    assert response.status_code == 401
    assert feedback_service.submissions == []


def test_submit_feedback_persists_the_owner_scoped_submission() -> None:
    client, feedback_service = _client()

    response = client.post(
        "/feedback",
        json={
            "category": "bug",
            "message": "The export button does nothing.",
            "context_path": "/agents/cv-expert",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert "created_at" in body
    assert feedback_service.submissions == [
        ("owner-1", "bug", "The export button does nothing.", "/agents/cv-expert")
    ]


def test_submit_feedback_rejects_an_empty_message() -> None:
    client, _ = _client()

    response = client.post("/feedback", json={"category": "feedback", "message": ""})

    assert response.status_code == 422


def test_submit_feedback_rejects_an_invalid_category() -> None:
    client, _ = _client()

    response = client.post("/feedback", json={"category": "compliment", "message": "Nice job."})

    assert response.status_code == 422


def test_submit_feedback_rejects_unknown_fields() -> None:
    client, _ = _client()

    response = client.post(
        "/feedback", json={"category": "bug", "message": "hi", "owner_id": "attacker"}
    )

    assert response.status_code == 422
