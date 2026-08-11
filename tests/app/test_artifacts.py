"""Generated artifacts are downloadable only by their authenticated owner."""

from __future__ import annotations

from uuid import uuid4

from artifact.controller import router
from artifact.service import ArtifactService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from tool.tools.local.markdown import generate_markdown

from shared.auth import AuthenticatedUser, AuthenticationError
from shared.types import ArtifactReference


class _Authenticator:
    async def authenticate(self, token: str | None) -> AuthenticatedUser:
        if token is None:
            raise AuthenticationError("A bearer access token is required.")
        return AuthenticatedUser(id=token)


class _FakeRepository:
    """Fake satisfying artifact.repository.ArtifactRepository's shape."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[bytes, str]] = {}
        self.owners: dict[str, str] = {}

    async def store(self, filename: str, content: bytes, content_type: str) -> None:
        if filename in self.records:
            raise IntegrityError("duplicate artifact filename", {}, Exception("duplicate"))
        self.records[filename] = (content, content_type)

    async def read(self, filename: str) -> tuple[bytes, str] | None:
        return self.records.get(filename)

    async def grant(self, user_id: str, artifacts: list[ArtifactReference]) -> None:
        self.owners.update({artifact.filename: user_id for artifact in artifacts})

    async def can_download(self, user_id: str, filename: str) -> bool:
        return self.owners.get(filename) == user_id


async def test_generated_artifact_download_is_authenticated_and_owner_scoped() -> None:
    test_app = FastAPI()
    artifact_service = ArtifactService(_FakeRepository())
    test_app.state.authenticator = _Authenticator()
    test_app.state.artifact_service = artifact_service
    test_app.include_router(router)

    requested_filename = f"download-test-{uuid4().hex}.md"
    result = await generate_markdown("# Download me", artifact_service, path=requested_filename)
    artifact = ArtifactReference.model_validate(result)
    await artifact_service.grant("user-1", [artifact])

    client = TestClient(test_app)
    response = client.get(
        result["download_url"],
        headers={"Authorization": "Bearer user-1"},
    )
    another_user = client.get(
        result["download_url"],
        headers={"Authorization": "Bearer user-2"},
    )
    unauthenticated = client.get(result["download_url"])
    write_attempt = client.post(
        result["download_url"],
        headers={"Authorization": "Bearer user-1"},
        content="replacement",
    )

    assert response.status_code == 200
    assert response.text == "# Download me"
    assert response.headers["content-type"].startswith("text/markdown")
    assert another_user.status_code == 404
    assert unauthenticated.status_code == 401
    assert write_attempt.status_code == 405
