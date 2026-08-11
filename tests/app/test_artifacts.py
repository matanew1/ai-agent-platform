"""Generated artifacts are downloadable but not writable through HTTP."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from tool.tools.markdown import generate_markdown

from app.main import app
from shared.artifacts import ARTIFACTS_URL_PATH


async def test_generated_artifact_is_downloadable_from_the_mounted_route() -> None:
    static_route = next(route for route in app.routes if route.path == ARTIFACTS_URL_PATH)
    assert isinstance(static_route.app, StaticFiles)

    requested_filename = f"download-test-{uuid4().hex}.md"
    result = await generate_markdown("# Download me", path=requested_filename)
    generated_path = Path(static_route.app.directory) / result["filename"]

    try:
        client = TestClient(app)
        response = client.get(result["download_url"])
        write_attempt = client.post(result["download_url"], content="replacement")

        assert response.status_code == 200
        assert response.text == "# Download me"
        assert response.headers["content-type"].startswith("text/markdown")
        assert write_attempt.status_code == 405
        assert generated_path.read_text() == "# Download me"
    finally:
        generated_path.unlink(missing_ok=True)
