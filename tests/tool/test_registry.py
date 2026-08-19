"""Unit tests for tool.service.ToolService.

Exercises ``register_local``/``get_tools``/``call_tool`` directly - against
hand-built definitions for the generic mechanics, and against the real
tool files in ``tool/tools/`` (no mocking needed - they're plain
functions) for the "does a real tool actually work" case. ``register_mcp``'s
own wiring is exercised end to end by ``tests/tool/test_mcp_adapter.py``,
mocked at the ``ClientSession`` boundary.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import pytest
from mcp import StdioServerParameters
from tool.service import RegisteredTool, ToolService
from tool.tools.local import markdown, pdf

from shared.types import ToolDefinition


async def _echo(**kwargs: object) -> dict[str, object]:
    return {"echo": kwargs}


async def _boom(**kwargs: object) -> object:
    raise ValueError("handler blew up")


def _make_definition(name: str = "echo") -> ToolDefinition:
    return ToolDefinition(name=name, description="Echoes its arguments.")


def test_register_local_makes_tool_visible_in_get_tools() -> None:
    registry = ToolService()
    registry.register_local(_make_definition(), _echo)

    names = [tool.name for tool in registry.get_tools()]

    assert names == ["echo"]


def test_register_local_tool_defaults_source_to_local() -> None:
    """Local tools carry ``source="local"`` without register_local needing to set it -
    it's ToolDefinition's own default (see shared/types.py)."""
    registry = ToolService()
    registry.register_local(_make_definition(), _echo)

    (tool,) = registry.get_tools()
    assert tool.source == "local"


def test_register_local_returns_the_registry_for_chaining() -> None:
    """Local registrations can be composed fluently at the app boundary."""
    registry = ToolService()

    returned_registry = registry.register_local(_make_definition(), _echo)

    assert returned_registry is registry


async def test_register_mcp_returns_the_registry_for_chaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP registrations return the registry after their awaited I/O step."""
    from tool.tools.mcp.adapter import McpServerAdapter

    registered_tool = RegisteredTool(definition=_make_definition(), handler=_echo)

    class FakeAdapter:
        """Minimal connected adapter for testing registry composition."""

        async def list_tools(self) -> list[RegisteredTool]:
            return [registered_tool]

    async def fake_connect(
        server_params: StdioServerParameters, exit_stack: AsyncExitStack, server_name: str
    ) -> FakeAdapter:
        return FakeAdapter()

    monkeypatch.setattr(McpServerAdapter, "connect", fake_connect)
    registry = ToolService()
    server_params = StdioServerParameters(command="fake-server")

    async with AsyncExitStack() as exit_stack:
        returned_registry = await registry.register_mcp(server_params, exit_stack, "fake")

    assert returned_registry is registry
    assert [tool.name for tool in registry.get_tools()] == ["echo"]


async def test_call_tool_invokes_the_registered_handler() -> None:
    registry = ToolService()
    registry.register_local(_make_definition(), _echo)

    result = await registry.call_tool("echo", {"message": "hi"})

    assert result.tool_name == "echo"
    assert result.content == {"echo": {"message": "hi"}}
    assert result.is_error is False


async def test_call_tool_returns_is_error_for_unknown_tool_name() -> None:
    registry = ToolService()

    result = await registry.call_tool("does_not_exist", {})

    assert result.is_error is True
    assert "does_not_exist" in str(result.content)


async def test_call_tool_returns_is_error_when_handler_raises() -> None:
    registry = ToolService()
    registry.register_local(_make_definition(name="boom"), _boom)

    result = await registry.call_tool("boom", {})

    assert result.tool_name == "boom"
    assert result.is_error is True
    assert "handler blew up" in str(result.content)


def test_register_local_replaces_existing_tool_with_same_name() -> None:
    registry = ToolService()
    registry.register_local(_make_definition(), _echo)
    registry.register_local(_make_definition(), _echo)  # same name - should replace

    assert len(registry.get_tools()) == 1


async def test_register_local_makes_a_real_tool_file_callable() -> None:
    registry = ToolService()
    registry.register_local(pdf.DEFINITION, pdf.extract_pdf)
    registry.register_local(pdf.GENERATE_DEFINITION, pdf.generate_pdf)
    registry.register_local(pdf.EDIT_DEFINITION, pdf.edit_pdf)
    registry.register_local(markdown.DEFINITION, markdown.extract_markdown)
    registry.register_local(markdown.GENERATE_DEFINITION, markdown.generate_markdown)
    registry.register_local(markdown.EDIT_DEFINITION, markdown.edit_markdown)

    names = {tool.name for tool in registry.get_tools()}
    assert names == {
        "extract_pdf",
        "generate_pdf",
        "edit_pdf",
        "extract_markdown",
        "generate_markdown",
        "edit_markdown",
    }

    result = await registry.call_tool("extract_markdown", {"path": "/nonexistent"})
    assert result.is_error is True  # handler ran for real and failed on a missing file
