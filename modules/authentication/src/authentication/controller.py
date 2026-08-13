"""The verified-caller FastAPI dependency and the backend-owned WorkOS AuthKit routes.

The whole OAuth round-trip (login redirect, code exchange, session cookie,
refresh, logout) lives here now - the frontend only ever calls these routes
and sends cookies, never WorkOS directly. Mounted from ``app/main.py`` like
every other module router.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable
from inspect import signature
from typing import Annotated, Any, cast
from urllib.parse import quote, unquote

from authentication.repository import (
    LOGIN_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthRepository,
    AuthSettings,
    DevelopmentAuthenticator,
    cookie_policy,
)
from authentication.schemas import MeResponse
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie

from shared.auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationUnavailableError,
)

logger = logging.getLogger(__name__)

_DEFAULT_RETURN_TO = "/agents"

# auto_error=False so a missing cookie reaches the manual check below (which
# raises the same 401 shape whether the cookie is absent or invalid) instead
# of FastAPI's own generic 403 - same reasoning the old HTTPBearer(
# auto_error=False) declaration used. Declared as a real Security scheme
# (rather than reading request.cookies directly) purely so this shows up
# correctly in the OpenAPI schema/Swagger UI, the same role HTTPBearer
# played for the bearer-token flow this replaced.
_session_cookie = APIKeyCookie(
    name=SESSION_COOKIE_NAME, auto_error=False, scheme_name="SessionCookie"
)


async def get_current_user(
    request: Request,
    response: Response,
    cookie_value: Annotated[str | None, Depends(_session_cookie)],
) -> AuthenticatedUser:
    """Verify the session cookie through the process-wide authenticator.

    A session refreshed mid-request (the embedded access token had expired
    but the refresh token was still valid) gets its rotated cookie re-set on
    this same ``response`` - FastAPI guarantees it's the object used to build
    the real outgoing response, so every route behind this dependency picks
    up the refresh for free, with no changes of its own.
    """
    authenticator: AuthRepository | DevelopmentAuthenticator | None = getattr(
        request.app.state, "authenticator", None
    )
    if authenticator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    try:
        result = await authenticator.authenticate_session(cookie_value)
        # Composition-level dependencies (notably the standalone tool router)
        # can authorize without importing this module's dependency while
        # still making the verified principal available to their handler.
        request.state.current_user = result.user
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except AuthenticationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if result.sealed_session and result.sealed_session != cookie_value:
        settings: AuthSettings = request.app.state.auth_settings
        response.set_cookie(
            SESSION_COOKIE_NAME,
            result.sealed_session,
            max_age=settings.session_cookie_max_age_seconds,
            **cookie_policy(settings.app_environment),
        )
    return result.user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def current_user(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Make an endpoint's ``current_user`` argument an auth dependency.

    Use directly beneath a FastAPI route decorator::

        @router.get("/resource")
        @current_user
        async def get_resource(current_user: AuthenticatedUser) -> Resource: ...

    FastAPI reads the endpoint signature while registering the route.  The
    decorator replaces only the named parameter's annotation with the typed
    ``Depends(get_current_user)`` declaration, leaving the handler's Python
    signature and its access to the verified principal unchanged.
    """
    endpoint_signature = signature(endpoint)
    parameter = endpoint_signature.parameters.get("current_user")
    if parameter is None:
        raise TypeError("@current_user requires a 'current_user' endpoint parameter.")

    authenticated_parameter = parameter.replace(annotation=CurrentUser)
    endpoint.__signature__ = endpoint_signature.replace(
        parameters=[
            authenticated_parameter if item.name == "current_user" else item
            for item in endpoint_signature.parameters.values()
        ]
    )
    return endpoint


def _safe_path(return_to: object) -> str:
    """Reduce an untrusted redirect target to a safe same-origin path.

    Mirrors the check the frontend used to do itself, client-side
    (``main.tsx``'s old ``onAuthRedirect``), before this flow moved
    server-side: a bare path only, never a full URL - ``//evil.example`` is a
    protocol-relative URL, not a path, so it's rejected like anything else
    that doesn't start with a single ``/``.
    """
    if not isinstance(return_to, str) or not return_to.startswith("/"):
        return _DEFAULT_RETURN_TO
    if return_to.startswith("//") or any(character in return_to for character in "\\\r\n"):
        return _DEFAULT_RETURN_TO
    return return_to


def _auth_error_redirect(frontend_url: str, return_to: str) -> RedirectResponse:
    """Build the shared "sign-in failed" redirect and clear the login-state cookie."""
    response = RedirectResponse(
        f"{frontend_url}{return_to}?auth_error=1", status_code=status.HTTP_302_FOUND
    )
    response.delete_cookie(LOGIN_STATE_COOKIE_NAME)
    return response


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(
    request: Request, return_to: str | None = None, screen_hint: str | None = None
) -> RedirectResponse:
    """Redirect the browser to WorkOS's hosted AuthKit sign-in page."""
    authenticator: AuthRepository | DevelopmentAuthenticator = request.app.state.authenticator
    settings: AuthSettings = request.app.state.auth_settings
    state = secrets.token_urlsafe(32)
    url = authenticator.login_url(state=state, screen_hint=screen_hint)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        LOGIN_STATE_COOKIE_NAME,
        # URL-encoded (safe="" - a bare quote() leaves "/" unescaped, which
        # is still enough to make Python's http.cookies module wrap the
        # value in RFC 6265 quoting) so the raw cookie value is a plain
        # token with no characters that need quoting - quoted cookie values
        # round-trip fine through real browsers but not transparently
        # through every HTTP client/proxy.
        quote(json.dumps({"state": state, "return_to": _safe_path(return_to)}), safe=""),
        max_age=settings.login_state_cookie_max_age_seconds,
        **cookie_policy(settings.app_environment),
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Exchange the authorization code and set the session cookie."""
    authenticator: AuthRepository | DevelopmentAuthenticator = request.app.state.authenticator
    settings: AuthSettings = request.app.state.auth_settings
    frontend_url = cast(str, settings.frontend_url)

    saved: dict[str, object] | None = None
    raw_state_cookie = request.cookies.get(LOGIN_STATE_COOKIE_NAME)
    if raw_state_cookie:
        try:
            saved = json.loads(unquote(raw_state_cookie))
        except ValueError:
            saved = None
    return_to = _safe_path(saved.get("return_to") if saved else None)

    if error or not code or not saved or saved.get("state") != state:
        logger.warning(
            "Auth callback rejected: error=%r has_code=%s state_ok=%s",
            error,
            bool(code),
            bool(saved),
        )
        return _auth_error_redirect(frontend_url, return_to)

    try:
        result = await authenticator.exchange_code(code)
    except (AuthenticationError, AuthenticationUnavailableError) as exc:
        logger.warning("Auth callback code exchange failed: %s", exc)
        return _auth_error_redirect(frontend_url, return_to)

    response = RedirectResponse(f"{frontend_url}{return_to}", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        result.sealed_session,
        max_age=settings.session_cookie_max_age_seconds,
        **cookie_policy(settings.app_environment),
    )
    response.delete_cookie(LOGIN_STATE_COOKIE_NAME)
    return response


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear the local session, end it on WorkOS's side too, then redirect.

    Plain browser-navigable GET, deliberately without a CSRF token: the
    worst a forged request here achieves is forcing a re-login (it can't
    read or mutate anything), and ``/auth/login`` necessarily has to be a
    bare GET too since a real browser has to land on it.
    """
    authenticator: AuthRepository | DevelopmentAuthenticator = request.app.state.authenticator
    settings: AuthSettings = request.app.state.auth_settings
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    target = await authenticator.logout_url(
        cookie_value, return_to=cast(str, settings.frontend_url)
    )
    response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/me", response_model=MeResponse)
@current_user
async def me(current_user: AuthenticatedUser) -> MeResponse:
    """Return the authenticated caller's identity.

    This route *is* the frontend's auth gate: a 401 here is exactly what it
    treats as "show sign-in", a 200 as "render the app".
    """
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )
