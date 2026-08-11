---
name: add-mcp-server
description: Add and evaluate a new external MCP server (mcp-servers.yaml) as an agent-callable tool source, following this repo's measured-accuracy standard
---

# Add an external MCP server

For a tool backed by a *separate process* speaking MCP over stdio (the
`fetch`/`time`/`duckduckgo` pattern) - not an in-process Python function
(that's `add-local-tool`). Full detail, including two servers evaluated and
rejected, lives in
[tool-conventions.md](../../rules/tool-conventions.md) - read it before
enabling a server this skill doesn't already cover, since the accuracy
numbers there are what any new server should be held to.

## Steps

1. **Add one entry to `modules/tool/src/tool/mcp/mcp-servers.yaml`** -
   `command`/`args`/optional `env`, plain data, no Python:
   ```yaml
   my_server:
     command: uvx
     args: ["--with", "mcp==1.9.4", "mcp-server-my-thing"]
   ```
   `app/lifespan.py` doesn't change - it registers every server
   `tool.mcp.config.load_servers()` finds, in a loop.

2. **Sanity-check outside the app first**: `uvx <package> --help`. This
   reproduces (or rules out) the one gotcha every server tried here has hit:
   the officially published servers are built against an older `mcp` SDK API
   than `uvx` resolves by default, and crash on startup unless the
   subprocess's own `mcp` install is pinned - `uvx --with mcp==1.9.4
   <server>`. Two failure shapes to recognize: `ImportError: cannot import
   name 'McpError'` (renamed to `MCPError` upstream), or `AttributeError:
   'Server' object has no attribute 'list_tools'`. Try unpinned first only
   to confirm the crash is real and worth documenting, then pin it.

3. **Start the app and confirm registration**: look for `Registered N
   tool(s) from MCP server command=...` in the startup log, then
   `GET /tools` to see the new tool(s) listed alongside the existing ones.

4. **Measure tool-selection accuracy before defaulting it on - this is not
   optional here.** Registering a tool costs more than its own
   functionality: it's LLM context the model has to read on *every* turn to
   decide what to call, and this repo has twice measured that adding one
   server degrades another, previously-reliable one's selection rate
   (`sqlite` dropped `get_current_time` from 3/3 to 2/3; `duckduckgo` from
   3/3 to 1/3). Run the same handful of prompts at least 3 times each, with
   and without the new server registered:
   - An existing reliable call (e.g. a `fetch` request) - did it regress?
   - `get_current_time` with no timezone given - the known-fragile case.
   - The new server's own obviously-correct-tool prompt (e.g. an explicit
     "search the web for..." for a search server).
   Record the results as a markdown table, the same shape as the `sqlite`/
   `duckduckgo` tables in tool-conventions.md, and add it to that file's
   "Servers evaluated" section - whether you end up enabling it or not.
   **A capability the agent reaches ~0-30% of the time, which also degrades
   one it previously reached reliably, is worse than no capability** - the
   established rule from that file. `duckduckgo` was enabled anyway despite
   failing this bar, but only because the capability itself (real-time web
   results) is one an LLM cannot fake from training data - that's the one
   accepted exception, not the default outcome.

5. **Security check.** Does the server mutate state (write access to a
   filesystem, a DB, a repo)? This app's `fetch` tool already pipes
   attacker-controlled web text into the model's prompt - a textbook
   prompt-injection channel - so pairing that with *any* write-capable tool
   is a compounding risk (this is why `git`'s 5 mutating tools were left
   disabled here). If the new server can write anywhere, say so explicitly
   when you document the decision, and prefer leaving it disabled unless
   there's a real, scoped need.

6. **Never special-case a server's name in code.** Argument massaging
   belongs in the YAML, not a branch in `tool/mcp/adapter.py` - a
   `tool_overrides` config layer was built for exactly this once and removed
   again once its only user went away (see tool-conventions.md). If a
   server's arguments need adjusting, that's a sign the YAML needs a new
   field, not `adapter.py` a new `if`.

7. **Verify:**
   ```bash
   uv run pytest tests/tool -q
   uv run ruff check .
   ```
   (No new Python to format/lint for a YAML-only addition, but re-run the
   suite - `tests/tool/test_mcp_config.py` parses the real file.)
