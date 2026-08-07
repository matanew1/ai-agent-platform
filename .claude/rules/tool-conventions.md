# Tool Conventions

## Ownership

All local tool code lives in `modules/tool/src/tool`. Every file sits at
the module root, no `internal/` (unlike `agent`/`rag` - see
[architecture.md](architecture.md#module-internal-layout) for why `tool`
is the exception): `registry.py` holds `ToolRegistry` (the module's public
entry point) and `RegisteredTool`; `decorator.py` holds the `@mcp_tool`
decorator that turns a plain async function into a registered tool;
`tools/` is where new local tools get added. `modules/agent` never knows a
tool's implementation - it only sees tools through the `ToolRegistry`
protocol it owns (`agent.internal.ports.ToolRegistry`), which
`tool.registry.ToolRegistry` satisfies. The two share a name on purpose
(concrete implementation named after the port it implements) and are
distinguished by module path, not name - `agent.internal.ports.ToolRegistry`
is the `Protocol`, `tool.registry.ToolRegistry` is what actually gets
constructed in `app/lifespan.py`.

```
agent -> (agent.internal.ports.ToolRegistry) -> tool.registry.ToolRegistry -> tool.tools/*
```

`tool` produces `ToolDefinition`/`ToolResult` shapes mirroring the Model
Context Protocol's tool schema (see `shared/types.py`) - that's what the
directory name `modules/mcp/` echoed originally - but backs them with
local Python functions only. There's no external MCP server integration
today; see "Implementation status" below.

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
  function or something else in the future.
- `ToolRegistry.call_tool` never raises for an unknown tool name or a
  failing handler - both come back as `ToolResult(is_error=True,
  content=...)`. This is deliberate: the caller is typically an LLM's
  freeform tool choice (see `agent.internal.graph.execute_tools`), not a
  hardcoded call, so "the LLM asked for a tool that doesn't exist" or "the
  tool ran but failed" are expected, recoverable outcomes, not exceptions
  to catch everywhere.
- New local tools are additive: add a file to `tool/tools/` with an
  `@mcp_tool`-decorated function and import it from `tool/tools/__init__.py`
  - nothing else changes. `ToolRegistry` and startup wiring
  (`app/lifespan.py`) don't know or care how many local tools exist.

## Implementation status

`tool` is fully implemented, not scaffolding - `extract_pdf` (via `pypdf`)
and `extract_markdown` (a small regex-based stripper, no dependency - see
[python-style.md](python-style.md) on not adding one for something this
simple) are both real, tested against real files (`tests/tool/test_tools.py`),
not mocked. There's no external-server integration or MCP SDK dependency
in this module - it was dropped along with `mcp_gateway.internal.client`/
`external.py` (previously verified live against
`@modelcontextprotocol/server-filesystem`) once the app's only real need
turned out to be local tools. Re-adding one later means reintroducing an
`mcp` SDK dependency and reconciling it with this module's own name (`tool`
was chosen specifically because it no longer collides with `import mcp` -
see `tool/__init__.py`'s docstring).
