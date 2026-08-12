# Authentication: development vs. production

This app authenticates through a **backend-owned** WorkOS AuthKit flow (the
["vanilla"](https://workos.com/docs/authkit/vanilla/python) flow, not the
client-side SDK): the backend (`modules/authentication`) owns the entire
OAuth round-trip and hands the frontend an `httponly` session cookie. The
frontend never talks to WorkOS directly and has no WorkOS-facing
configuration of its own - it only calls this backend's `/auth/*` routes and
sends cookies (`credentials: "include"`).

```
Browser --GET /auth/login--> Backend --302--> WorkOS hosted sign-in
Browser <--302 (session cookie set)-- Backend <--GET /auth/callback?code=...-- WorkOS
```

## The four routes

| Route | What it does |
|---|---|
| `GET /auth/login` | Redirects to WorkOS's hosted AuthKit sign-in page. `?return_to=/path` controls where the user lands after signing in; `?screen_hint=sign-up` opens the sign-up view instead. |
| `GET /auth/callback` | WorkOS redirects here with `?code=...`. Exchanges the code, sets the session cookie, redirects to the frontend. Registered with WorkOS as the app's Redirect URI. |
| `GET /auth/logout` | Clears the local session, ends it on WorkOS's side too, redirects to the frontend. |
| `GET /auth/me` | Returns the signed-in user, or `401`. This *is* the frontend's auth gate (see `AuthGate.tsx`). |

## Environment variables

| Variable | Dev | Prod |
|---|---|---|
| `APP_ENV` | `development` | anything else (`production` by convention) |
| `AUTH_MODE` | `workos` (or `development` for an offline bypass, see below) | `workos` always |
| `WORKOS_CLIENT_ID` / `WORKOS_API_KEY` | Sandbox/Development credentials | Production credentials (a **separate** WorkOS environment/keypair) |
| `WORKOS_COOKIE_PASSWORD` | `openssl rand -base64 32` | A **different** generated value - don't reuse dev's |
| `AUTH_REDIRECT_URI` | `http://localhost:8000/auth/callback` | `https://api.yourdomain.com/auth/callback` - **must** be `https://` |
| `AUTH_FRONTEND_URL` | `http://localhost:5173` | `https://app.yourdomain.com` |
| `APP_CORS_ORIGINS` | `http://localhost:5173` | Your real frontend origin(s) - never `*` |

Copy the matching template and fill in the blanks:

```bash
cp .env.dev .env      # local development
# or, on your hosting platform, set .env.prod's variables directly
# (don't ship .env.prod itself - it's a template, not a secrets file)
```

### Why `APP_ENV` matters beyond just a label

`AuthSettings.from_environment()` (`modules/authentication/src/authentication/repository.py`)
reads it to decide two concrete things:

1. **Whether `AUTH_REDIRECT_URI` must be `https://`.** Startup fails closed
   (`RuntimeError`) if it isn't, outside `APP_ENV=development` - this is the
   exact error you'll hit if `.env` still says `APP_ENV=production` while
   `AUTH_REDIRECT_URI` points at `http://localhost:8000`.
2. **Cookie flags** (`cookie_policy()` in the same file):

   | | `APP_ENV=development` | otherwise |
   |---|---|---|
   | `Secure` | off | on |
   | `SameSite` | `Lax` | `None` |

   `localhost:5173` and `localhost:8000` are *same-site* (same host, only
   the port differs), so `SameSite=Lax` cookies flow between them over
   plain HTTP without needing `Secure`. A real deployment almost always has
   the frontend and backend on different domains - genuinely cross-site -
   which needs both `SameSite=None` and `Secure`, and `Secure` cookies are
   simply not sent over `http://` by any browser. This is why production
   *must* be HTTPS end to end, not just a preference.

## WorkOS Dashboard setup (do this for **each** environment - Sandbox/Dev and Production are separate credential sets)

Under your application's **Redirects** tab:

- **Redirect URIs**: add your `AUTH_REDIRECT_URI` value exactly
  (`http://localhost:8000/auth/callback` in dev, `https://api.yourdomain.com/auth/callback`
  in prod). WorkOS rejects the authorize call on any mismatch - scheme,
  host, port, and trailing slash all count.
- **Sign-out redirect** (and it doesn't hurt to also set App homepage URL /
  Initiate login URI): your `AUTH_FRONTEND_URL` value.

If you only see `http://localhost:5173` registered and nothing for
`:8000/auth/callback`, sign-in will fail at WorkOS's end even though the
backend boots fine - add it before testing.

## Local offline bypass (no WorkOS Dashboard access needed)

For local dev when you don't want to touch WorkOS at all:

```bash
APP_ENV=development
AUTH_MODE=development
AUTH_DEV_USER_ID=local-dev
```

Every request is authenticated as `AUTH_DEV_USER_ID`, no cookie or network
round-trip involved. `/auth/login` and `/auth/callback` are unreachable in
this mode (they raise `RuntimeError` if hit, by design - `/auth/me` never
`401`s, so the frontend never links to them). Both gates
(`APP_ENV=development` **and** `AUTH_MODE=development`) are required; this
refuses to activate under any other `APP_ENV`.

## Troubleshooting

- **`RuntimeError: AUTH_REDIRECT_URI must use HTTPS outside local
  development`** - `APP_ENV` isn't `development` but `AUTH_REDIRECT_URI` is
  `http://`. Either set `APP_ENV=development` for local work, or switch to
  a real `https://` URL for anything else. Check for a stray `APP_ENV`
  *exported* in your shell (`echo $APP_ENV`) overriding `.env` - real
  environment variables always win over `.env` (`load_dotenv(override=False)`).
- **Redirected to WorkOS, then back with `?auth_error=1`** - almost always
  a Dashboard mismatch: `AUTH_REDIRECT_URI` isn't registered under
  Redirects, or you're using Sandbox credentials against a Production
  Dashboard entry (or vice versa).
- **Signed in, but `/auth/me` still 401s on the next request (cross-origin
  frontend/backend)** - check the cookie's actual flags in DevTools. If
  `SameSite=None` isn't paired with `Secure`, the browser silently drops
  it; that pairing only happens automatically when `APP_ENV` isn't
  `development` (see the table above) - don't run a real cross-domain
  deployment with `APP_ENV=development`.
- **CORS error on `/auth/*` or any API call** - `APP_CORS_ORIGINS` must
  list the frontend's exact origin. It can never be `*` here:
  `allow_credentials=True` is always on (a session cookie exists), and
  Starlette reflects the literal request `Origin` instead of a wildcard
  when credentials are allowed - a wildcard would let any website ride a
  signed-in user's session.
