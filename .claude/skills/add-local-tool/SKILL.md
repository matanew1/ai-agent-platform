---
name: add-local-tool
description: Add a new in-process tool (pdf/markdown-style) to modules/tool/src/tool/tools/ and wire it into the registry
---

# Add a local tool

For a Python function that runs in-process (no external server) - the
`extract_pdf`/`extract_markdown` pattern. If this needs to call an *external*
MCP server instead, use `add-mcp-server`, not this skill.

Full rationale lives in
[tool-conventions.md](../../rules/tool-conventions.md) and
[architecture.md](../../rules/architecture.md#module-internal-layout) ("`tool`
has no `internal/`") - this skill is the checklist, not a restatement.

## Steps

1. **One new file, `modules/tool/src/tool/tools/<name>.py`.** Nothing else in
   `tool/tools/` changes - this is additive by design. It needs exactly two
   things, no decorator, nothing self-registering:
   - A module-level `DEFINITION: ToolDefinition` (see `shared/types.py`):
     - `name`: specific and action-oriented (`search_documents`,
       `create_ticket`) - never generic (`run`, `do_thing`).
     - `description`: complete - what it does, when to use it, what it
       returns. This is the *only* thing the LLM sees when deciding whether
       to call it; a vague description produces wrong tool calls.
     - `parameters`: a real JSON-schema object (`type`/`properties`/
       `required`), never a loose `dict[str, Any]` passed straight through.
   - A plain `async def <handler>(...) -> object` matching those parameters.
     Wrap any blocking I/O in `asyncio.to_thread` (see `pdf.py`'s
     `PdfReader` call) - don't block the event loop.

2. **Register it in `app/lifespan.py`** (SECTION 3), one line, alongside the
   existing calls:
   ```python
   tool_registry = (
       ToolRegistry()
       .register_local(pdf.DEFINITION, pdf.extract_pdf)
       .register_local(markdown.DEFINITION, markdown.extract_markdown)
       .register_local(<name>.DEFINITION, <name>.<handler>)
   )
   ```
   It isn't agent-callable until this line exists - the file alone does
   nothing.

3. **If the tool touches an infrastructure resource** (DB, cache, network,
   hosted API), go through `infrastructure/`, not ad hoc inside the tool
   file - see CLAUDE.md's "New dependencies on infrastructure resources"
   rule. A tool depending on its *own* core library (like `tool` already
   depends on `pypdf`) is fine and is not this case.

4. **Security check before shipping, especially for anything filesystem- or
   network-facing:** does the handler take a raw path/URL argument straight
   from the LLM's tool call with no validation? `extract_pdf`/
   `extract_markdown` currently don't sandbox `path` at all (a known,
   flagged gap - arbitrary local file read) - don't repeat that pattern
   without at least considering an allowlisted base directory. Also
   remember `POST /tools/{name}` (`tool/api/router.py`) lets any HTTP caller
   invoke this tool directly and unauthenticated, bypassing the agent's own
   tool-call mediation entirely.

5. **Tests.** Add to `tests/tool/test_tools.py` or a new file, mirroring the
   real-files-no-mocking pattern already there - a local tool with no
   external dependency should be tested against real inputs, not fakes.

6. **Verify:**
   ```bash
   uv run ruff format .
   uv run ruff check .
   uv run pytest tests/tool -q
   ```
