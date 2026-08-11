"""Coverage for the CORS middleware wired up in ``app/main.py``.

``_cors_origins`` parses ``APP_CORS_ORIGINS`` (comma-separated, "*" default)
into the list ``CORSMiddleware`` is constructed with - the one bit of actual
logic in that wiring, otherwise untested.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_wildcard_origin_is_allowed_by_default() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "https://example.com"})

    assert response.headers["access-control-allow-origin"] == "*"


def test_preflight_request_is_permitted_for_any_method_and_header() -> None:
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_stream_metadata_headers_are_exposed_to_browser_clients() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "https://example.com"})

    raw_headers = response.headers["access-control-expose-headers"]
    exposed = {header.strip().lower() for header in raw_headers.split(",")}
    assert exposed == {
        "x-tools-invoked",
        "x-chunks-retrieved",
        "x-prep-time-seconds",
        "x-artifacts",
    }
