# API Conventions

- Mount routers from `app/main.py`; module handlers access constructed
  services through `request.app.state`, never by importing the app instance.
- Keep routes `async`, thin, and Pydantic-backed. Request/response schemas
  live with their route/module and do not expose SQLAlchemy/domain models.
- Every non-public route uses the backend session-cookie authentication
  dependency. Derive ownership from `CurrentUser`; validate that the requested
  agent or artifact belongs to that user before accessing it.
- Return errors as `{"detail": "..."}`. Let FastAPI/Pydantic return 422 for
  malformed shapes; translate infrastructure exceptions before they reach the
  client.
- Chat streams use `text/plain`. Optional preparation metadata is carried in
  named `X-*` headers and must remain optional: a malformed metadata header
  must not invalidate the answer stream. Any new header consumed by the web
  client must be added to CORS `expose_headers` and covered by a route/CORS
  test.
- Documents are exposed under `/documents`, not nested under an agent. They
  are shared by the authenticated user's agents; the server owns all source
  IDs and owner metadata.
