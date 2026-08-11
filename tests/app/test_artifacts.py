"""Generated artifacts are downloadable only by their authenticated owner."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tool.tools.markdown import generate_markdown

from app.artifacts import router
from shared.artifacts import get_artifacts_directory
from shared.auth import AuthenticatedUser, AuthenticationError
from shared.types import ArtifactReference


class _Authenticator:
    async def authenticate(self, token: str | None) -> AuthenticatedUser:
        if token is None:
            raise AuthenticationError("A bearer access token is required.")
        return AuthenticatedUser(id=token)


class _Access:
    def __init__(self) -> None:
        self.owners: dict[str, str] = {}

    async def grant(self, user_id: str, artifacts: list[ArtifactReference]) -> None:
        self.owners.update({artifact.filename: user_id for artifact in artifacts})

    async def can_download(self, user_id: str, filename: str) -> bool:
        return self.owners.get(filename) == user_id


async def test_generated_artifact_download_is_authenticated_and_owner_scoped() -> None:
    test_app = FastAPI()
    access = _Access()
    test_app.state.authenticator = _Authenticator()
    test_app.state.artifact_access = access
    test_app.include_router(router)

    requested_filename = f"download-test-{uuid4().hex}.md"
    result = await generate_markdown("# Download me", path=requested_filename)
    generated_path = get_artifacts_directory() / Path(result["filename"])
    artifact = ArtifactReference.model_validate(result)
    await access.grant("user-1", [artifact])

    try:
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
        assert generated_path.read_text() == "# Download me"
    finally:
        generated_path.unlink(missing_ok=True)
