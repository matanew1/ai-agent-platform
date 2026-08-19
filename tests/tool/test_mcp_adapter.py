"""Unit tests for tool.tools.mcp.adapter.McpServerAdapter.

Mocked at the ClientSession boundary - the actual stdio connection
(`McpServerAdapter.connect`) is I/O, the same kind of thing verified live
rather than unit-tested elsewhere in this project (see
`.claude/rules/testing.md`'s treatment of infrastructure adapters). What's
tested here is `list_tools` and the handlers it builds, fed a
hand-written fake session - the adapter doesn't know what a ToolService
is, so there's nothing to mock beyond the session itself.
"""

from __future__ import annotations

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from tool.tools.mcp.adapter import McpServerAdapter


class FakeClientSession:
    """Fake standing in for mcp.ClientSession - only the two methods
    McpServerAdapter actually calls.
    """

    def __init__(self, tools: list[Tool], results: dict[str, CallToolResult]):
        self._tools = tools
        self._results = results
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_tools(self) -> ListToolsResult:
        return ListToolsResult(tools=self._tools)

    async def call_tool(self, name: str, arguments: dict[str, object]) -> CallToolResult:
        self.calls.append((name, arguments))
        return self._results[name]


def _remote_tool(name: str = "fetch", description: str = "Fetch a URL.") -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={"type": "object", "properties": {"url": {"type": "string"}}},
    )


async def test_list_tools_exposes_remote_tool_definitions() -> None:
    session = FakeClientSession(tools=[_remote_tool()], results={})

    tools = await McpServerAdapter(session, "fetch").list_tools()

    assert len(tools) == 1
    assert tools[0].definition.name == "fetch"
    assert tools[0].definition.description == "Fetch a URL."
    assert tools[0].definition.parameters == {
        "type": "object",
        "properties": {"url": {"type": "string"}},
    }
    assert tools[0].definition.source == "fetch"


async def test_list_tools_stamps_the_adapter_s_server_name_as_source() -> None:
    """Every tool from one server carries that server's mcp-servers.yaml key, for
    the web UI's Tool Registry grouping (source is display metadata only, not sent
    to the LLM - see ToolDefinition.source's docstring).
    """
    session = FakeClientSession(tools=[_remote_tool(name="get_current_time")], results={})

    (tool,) = await McpServerAdapter(session, "time").list_tools()

    assert tool.definition.source == "time"


async def test_adapted_tool_calls_the_remote_tool_and_flattens_text_content() -> None:
    session = FakeClientSession(
        tools=[_remote_tool()],
        results={
            "fetch": CallToolResult(
                content=[TextContent(type="text", text="page content")], isError=False
            )
        },
    )
    (tool,) = await McpServerAdapter(session, "fetch").list_tools()

    result = await tool.handler(url="https://example.com")

    assert result == "page content"
    assert session.calls == [("fetch", {"url": "https://example.com"})]


async def test_adapted_tool_raises_when_the_remote_tool_reports_an_error() -> None:
    """ToolService.call_tool turns a raised exception into
    ToolResult(is_error=True, ...) - see registry.py - so the handler
    raises here rather than returning error content directly.
    """
    session = FakeClientSession(
        tools=[_remote_tool()],
        results={
            "fetch": CallToolResult(
                content=[TextContent(type="text", text="fetch failed: 404")], isError=True
            )
        },
    )
    (tool,) = await McpServerAdapter(session, "fetch").list_tools()

    with pytest.raises(RuntimeError, match="fetch failed: 404"):
        await tool.handler(url="https://example.com/missing")


async def test_arguments_reach_the_remote_tool_exactly_as_the_agent_passed_them() -> None:
    """Nothing rewrites arguments on the way through - the agent's own
    choice per call is the whole contract (see mcp-servers.yaml's comment
    on fetch's raw/markdown tradeoff, which is decided that way and not by
    config).
    """
    session = FakeClientSession(
        tools=[_remote_tool()],
        results={
            "fetch": CallToolResult(
                content=[TextContent(type="text", text="<title>Example</title>")], isError=False
            )
        },
    )
    (tool,) = await McpServerAdapter(session, "fetch").list_tools()

    await tool.handler(url="https://example.com", raw=True)

    assert session.calls == [("fetch", {"url": "https://example.com", "raw": True})]


async def test_adapted_tool_joins_multiple_text_blocks_into_a_list() -> None:
    session = FakeClientSession(
        tools=[_remote_tool()],
        results={
            "fetch": CallToolResult(
                content=[
                    TextContent(type="text", text="part one"),
                    TextContent(type="text", text="part two"),
                ],
                isError=False,
            )
        },
    )
    (tool,) = await McpServerAdapter(session, "fetch").list_tools()

    result = await tool.handler(url="https://example.com")

    assert result == ["part one", "part two"]
