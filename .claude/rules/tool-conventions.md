# Tool Conventions

## Ownership

All tool code lives in `modules/tool/src/tool`, no `internal/` (unlike
`agent`/`rag` - see [architecture.md](architecture.md#module-internal-layout)
for why `tool` is the exception): `registry.py` holds `ToolRegistry` (the
module's public entry point) and `RegisteredTool`. Below it, tools split
into two sibling packages by where they come from, not by anything
agent-visible - and both are wired into a registry the same explicit way,
no decorators or import-time side effects either side:

- `tools/` - in-process Python functions. Each file (`pdf.py`, `markdown.py`
  today) defines a module-level `DEFINITION` (`ToolDefinition`) and a plain
  async handler - nothing self-registers. `ToolRegistry.register_local(
  DEFINITION, handler)` is what makes one agent-callable, called once per
  tool from `app/lifespan.py`.
- `mcp/` - tools adapted from an external MCP server, config-driven:
  `mcp/mcp-servers.yaml` is one file with one top-level entry per server -
  plain data, no Python (see "Implementation status" below);
  `mcp/config.py::load_servers()` parses every entry into
  `mcp.StdioServerParameters`; `mcp/adapter.py`'s `McpServerAdapter` class
  connects to one and turns its tools into `RegisteredTool`s.
  `ToolRegistry.register_mcp(server_params, exit_stack)` is
  `register_local`'s counterpart - same "one call per tool source from
  `app/lifespan.py`" shape, just `async`/awaited, since connecting to a
  server is I/O a local tool doesn't need.

`modules/agent` never knows a tool's implementation - it only sees tools
through the `ToolRegistry` protocol it owns
(`agent.internal.ports.ToolRegistry`), which `tool.registry.ToolRegistry`
satisfies. The two share a name on purpose (concrete implementation named
after the port it implements) and are distinguished by module path, not
name - `agent.internal.ports.ToolRegistry` is the `Protocol`,
`tool.registry.ToolRegistry` is what actually gets constructed, once, in
`app/lifespan.py`.

```
agent -> (agent.internal.ports.ToolRegistry) -> tool.registry.ToolRegistry -> tool.tools / tool.mcp
```

`tool` produces `ToolDefinition`/`ToolResult` shapes mirroring the Model
Context Protocol's tool schema (see `shared/types.py`) - that's what the
directory name `modules/mcp/` echoed originally, before this module was
renamed to `tool` (see `tool/__init__.py`'s docstring on why: `import mcp`
- the actual MCP Python SDK - no longer collides with a module named
`tool`, which matters now that `tool/mcp/adapter.py` really does
`import mcp`).

## Tool definitions

- Every tool exposed to the agent has a clear, complete description — what
  it does, when to use it, and what it returns. The description is what the
  LLM uses to decide whether to call the tool; a vague description produces
  wrong tool calls.
- Tool arguments are typed and validated (Pydantic model or equivalent
  JSON-schema-backed type), never a loose `dict[str, Any]` passed straight
  through to the handler.
- Tool names are specific and action-oriented (`search_documents`,
  `create_ticket`), not generic (`run`, `do_thing`).

## Boundary discipline

- The agent should not know a tool's implementation. It calls a tool by name
  with typed arguments (`ToolRegistry.call_tool`) and gets a typed
  `ToolResult` back — it doesn't know whether that tool is a local Python
  function, an external MCP server, or something else in the future.
- `ToolRegistry.call_tool` never raises for an unknown tool name or a
  failing handler - both come back as `ToolResult(is_error=True,
  content=...)`. This is deliberate: the caller is typically an LLM's
  freeform tool choice (see `agent.internal.graph.execute_tools`), not a
  hardcoded call, so "the LLM asked for a tool that doesn't exist" or "the
  tool ran but failed" are expected, recoverable outcomes, not exceptions
  to catch everywhere. `tool/mcp/adapter.py`'s handler follows the same
  contract from the other direction: it *raises* when the remote server
  reports its own tool-level error (`CallToolResult.is_error`), rather than
  inventing a second error channel, so that raise lands in this same
  `call_tool` catch and comes out the door as `is_error=True` either way.
- New local tools are additive: add a file to `tool/tools/` with a
  `DEFINITION` constant and a plain async handler function (see `pdf.py`)
  - nothing else in `tool/tools/` changes. It isn't agent-callable until
  something calls `registry.register_local(DEFINITION, handler)` -
  `app/lifespan.py` is that one call site, one line per tool.
- New external-MCP-server-backed tools are the most additive of all: add
  an entry to `tool/mcp/mcp-servers.yaml` (see the `fetch` entry) with the
  server's `command`/`args`. `app/lifespan.py` doesn't change - it
  registers every server `tool.mcp.config.load_servers()` finds, in a
  loop. Neither does `adapter.py`, the same open/closed property `tools/`
  gives local tools - and if a server ever needs its arguments massaged,
  that belongs in the YAML for the same reason, not in a branch there.

## Implementation status

`tool` is fully implemented, not scaffolding - `extract_pdf` (via `pypdf`)
and `extract_markdown` (a small regex-based stripper, no dependency - see
[python-style.md](python-style.md) on not adding one for something this
simple) are both real, tested against real files (`tests/tool/test_tools.py`),
not mocked.

External MCP server integration was dropped early on (`mcp_gateway.internal
.client`/`external.py`, previously verified live against
`@modelcontextprotocol/server-filesystem`) once the app's only real need
turned out to be local tools, then re-added once a second real need showed
up: `tool/mcp/mcp-servers.yaml`'s `fetch` entry configures the official
Fetch MCP server (`mcp-server-fetch`, run via `uvx` - no Node/npm
dependency), which exposes a `fetch` tool (fetch a URL, return its content
as text) alongside the local tools.

- `tool/mcp/config.py::load_servers()` parses every top-level entry in
  `tool/mcp/mcp-servers.yaml` into a `mcp.StdioServerParameters` (`command`
  + `args` + optional `env`) - one file, plain data, no Python needed to
  add a server. Tested against the real file in
  `tests/tool/test_mcp_config.py` (no mocking - it's just local file
  parsing).
- Arguments reach a remote tool exactly as the agent passed them; nothing
  rewrites them in between. A `tool_overrides` config layer (per-tool
  forced argument values, declared in `mcp-servers.yaml`) was built here
  and then removed once its only user went away - the same
  "don't keep a capability just in case" call this module already made
  once with its external-server client. Two things from it are worth
  keeping written down:

  - It had to **override** what the agent sent, not merely fill in what it
    omitted. Filling in omissions was tried first and did nothing at all,
    because the LLM reads each parameter's advertised `default` out of the
    tool schema and passes it back explicitly - observed as
    `call_tool name='fetch' argument_keys=['url', 'raw']` with
    `raw=false`, on a turn where nothing asked for markdown. Any future
    per-tool config that fights a schema default needs the same direction.
  - It belongs in the YAML, not in a branch inside `adapter.py`. The
    moment `adapter.py` learns one specific server's name, the
    "new server = YAML only" property is gone.

- `mcp-server-fetch`'s `raw` argument is the concrete case that prompted
  all of the above, and it stays the agent's per-call choice. Default
  (`raw: false`) converts the page to markdown, which drops `<head>` and
  with it the `<title>` - so "tell me the page title" alone gets "the
  title could not be extracted", which looks like a broken tool and isn't.
  Forcing `raw: true` globally fixes titles and costs far more than it
  looks: measured on the same page at the same `max_length`, markdown gave
  260 readable words and raw gave 8, because raw HTML spends the budget on
  `<head>`/`<script>` boilerplate before reaching any prose. Markdown is
  the better default for a tool whose main job is answering about page
  *content*; a request that actually needs markup just says so, and the
  agent passes `raw: true` itself (verified live - it returns the exact
  `<title>`). The numbers live in `mcp-servers.yaml`'s comment too, next
  to the setting.
- `tool/mcp/adapter.py`'s `McpServerAdapter` is the reusable connection
  piece and doesn't know what a `ToolRegistry` is: construct it directly
  with an already-initialized `mcp.ClientSession` and call `list_tools()`
  to get back a `list[RegisteredTool]` - this is what's unit-tested,
  against a fake session, in `tests/tool/test_mcp_adapter.py`; its
  `connect` classmethod owns the actual stdio connection instead
  (exercised live rather than unit-tested, the same treatment
  [testing.md](testing.md) gives every other I/O-doing adapter).
- `ToolRegistry.register_mcp` is what ties the two together - it calls
  `McpServerAdapter.connect` then stores what `list_tools()` returns.

A second server, `time` (`mcp-server-time`: `get_current_time`,
`convert_time`), is enabled alongside it. It earns its place on the one
axis an LLM cannot fake - it has no clock, and its training cutoff is not
"now" - and it costs nothing to secure: no filesystem, no network, no
arguments beyond a timezone, computed from the host clock and the tz
database.

This does mean the module depends on both the `mcp` SDK (see "Ownership"
above for why that no longer collides with this module's own name) and
`pyyaml` again.

## Servers evaluated and not enabled

Two more official servers were wired up, connected to, and called for
real before being left out. Both work; neither is off for a vague reason.
Re-enabling either is a YAML entry, nothing more.

**sqlite** (`--with mcp==1.9.4 mcp-server-sqlite --db-path <file>`) -
6 tools: `read_query`, `write_query`, `create_table`, `list_tables`,
`describe_table`, `append_insight`. Connects fine and answers direct
calls correctly. The problem is upstream of the protocol: `qwen3:8b`
will not reliably *choose* these tools. Measured, 3 trials each, same
prompt template:

| registered tools | `fetch` | `get_current_time` | `read_query` | `list_tables` |
| --- | --- | --- | --- | --- |
| fetch only (3) | 3/3 | - | - | - |
| fetch + time (5) | 3/3 | 3/3 | - | - |
| fetch + time + sqlite (11) | 3/3 | **2/3** | 1/3 | 0/3 |
| sqlite alone (6) | - | - | 0/3 | 0/3 |

The last row is the important one: sqlite's own tools fail 0/3 *with no
other server present* and a **smaller** prompt (1,667 chars, vs 2,065 for
the fetch-only baseline), so this is not a tool-count or context-length
ceiling. The descriptions are clear and render correctly ("List all tables
in the SQLite database" against the request "List all the tables in the
database"), and the model still answers `[]`. Row 3 is the cost of
enabling it anyway: it dragged `get_current_time` down from 3/3 to 2/3.
A capability the agent reaches ~0-30% of the time, which also degrades one
it previously reached reliably, is worse than no capability - the failure
mode is a confident wrong answer, not an error. Worth retrying behind a
larger model; the accuracy table above is the way to check.

**git** (`--with mcp==1.9.4 mcp-server-git --repository <path>`) -
12 tools, verified live (`git_status` returned this repo's real status).
Left off for a security reason rather than an accuracy one: 5 of the 12
mutate a repository (`git_commit`, `git_add`, `git_reset`,
`git_checkout`, `git_create_branch`), and this agent already runs `fetch`,
which pipes attacker-controlled text off the public web directly into the
model's prompt (`format_tool_results` -> `GENERATE_ANSWER_PROMPT_TEMPLATE`).
That is a textbook prompt-injection channel, and pairing it with write
access to a working tree means a fetched page can attempt repository
mutations. Enable it only with that pairing in mind - ideally against a
throwaway clone, not the checkout you work in.

The general rule both cases point at: a tool the agent can reach is part
of the app's attack surface *and* part of its accuracy budget. Adding one
is cheap (a YAML entry); justifying one is not. Measure selection accuracy
before and after - `_mentions_a_tool` and the tool-call prompt both scale
with the registered set.

`ToolRegistry` itself is built exactly once, in `app/lifespan.py`, the
same "construct once at the composition root" rule as every other service
here ([architecture.md](architecture.md#dependency-injection)) - not a
module-level singleton, not per-request:

```python
tool_registry = ToolRegistry()
tool_registry.register_local(pdf.DEFINITION, pdf.extract_pdf)
tool_registry.register_local(markdown.DEFINITION, markdown.extract_markdown)
for server in load_servers():
    await tool_registry.register_mcp(server, mcp_exit_stack)
```

`register_mcp` is the only one that's `await`ed - connecting to an
external process is the only step here that's actually I/O; everything
else is plain function references and dict lookups, so there's nothing to
make async. `mcp_exit_stack` (an `AsyncExitStack`) keeps every such
connection - and therefore its tools - alive for the process's lifetime,
closed at shutdown alongside the other infrastructure connections.

One real gotcha, and it is not a one-off - assume any new server has it.
The officially published servers are built against an older `mcp` SDK API
than `uvx` resolves by default, so they crash on startup unless the
*subprocess's own* `mcp` install is pinned: `uvx --with mcp==1.9.4
<server>`. That pin is separate from this project's own (newer) `mcp`
client dependency; the two only talk over stdio/JSON-RPC, so they don't
need to match. All four servers tried here needed it, in two flavours:

- `fetch`, `time` - `ImportError: cannot import name 'McpError'` (renamed
  to `MCPError` in a newer release).
- `sqlite`, `git` - `AttributeError: 'Server' object has no attribute
  'list_tools'` / `'list_resources'`.

Check a new server with a plain `uvx <package> --help` first: it
reproduces the crash outside this app, which is how the original was
diagnosed.
