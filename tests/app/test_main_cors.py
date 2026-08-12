"""Coverage for the CORS middleware wired up in ``app/main.py``.

``_cors_origins`` parses ``APP_CORS_ORIGINS`` (comma-separated, defaulting to
the local frontend's origin) into the list ``CORSMiddleware`` is constructed
with - the one bit of actual logic in that wiring, otherwise untested.
``allow_credentials=True`` is load-bearing now that ``authentication.
controller`` issues a session cookie (see its module docstring and the
comment above the middleware in ``app/main.py``), so this file also proves
an origin *outside* the allowlist gets no CORS headers at all - unlike the
old wildcard default, which allowed everyone.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

_ALLOWED_ORIGIN = "http://localhost:5173"


def test_allowed_origin_is_echoed_back_with_credentials_enabled() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": _ALLOWED_ORIGIN})

    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_origin_outside_the_allowlist_gets_no_cors_headers() -> None:
    """Not a wildcard anymore: allow_credentials=True makes an open allowlist unsafe."""
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "https://attacker.example"})

    assert "access-control-allow-origin" not in response.headers


def test_preflight_request_is_permitted_for_the_allowed_origin() -> None:
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": _ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_stream_metadata_headers_are_exposed_to_browser_clients() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": _ALLOWED_ORIGIN})

    raw_headers = response.headers["access-control-expose-headers"]
    exposed = {header.strip().lower() for header in raw_headers.split(",")}
    assert exposed == {
        "x-tools-invoked",
        "x-chunks-retrieved",
        "x-prep-time-seconds",
        "x-artifacts",
    }
