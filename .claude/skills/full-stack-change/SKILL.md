---
name: full-stack-change
description: Implement a coordinated change across ai-agent-platform and its sibling React client, ai-agent-platform-web. Use when a user-visible feature changes a FastAPI endpoint, streaming metadata/header, authentication behavior, persisted data, or the web UI that consumes it.
---

# Full-stack change

The backend lives here; the web client is `../ai-agent-platform-web`. Treat
them as separate worktrees and preserve unrelated changes in either one.

1. Inspect the relevant route/schema/service and the corresponding web API,
   hook, and component before deciding the contract. Do not duplicate an API
   type by guesswork.
2. Keep authority on the backend: derive `owner_id` from `CurrentUser`, verify
   the agent belongs to that user before accessing its state, and never accept
   ownership or authorization fields from the browser.
3. For streamed endpoints, keep the text body usable even when optional
   metadata is malformed. Add new browser-read headers to the backend CORS
   `expose_headers` list, parse them defensively in the web client, and add a
   backend contract test.
4. If a change writes user-visible data, update the client state after the
   confirmed server response and retain the server's raw identifier for
   delete/update operations. A display label must not replace a secure source
   identifier.
5. Test both sides: run focused backend tests plus `uv run pytest -q` when
   practical, then run `npm run build` in `../ai-agent-platform-web`. Update
   either README when behavior, local setup, or storage semantics changed.
