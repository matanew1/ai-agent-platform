"""Unit tests for tool.registry.ToolRegistry.

Exercises ``register_local``/``get_tools``/``call_tool`` directly - against
hand-built definitions for the generic mechanics, and against the real
tool files in ``tool/tools/`` (no mocking needed - they're plain
functions) for the "does a real tool actually work" case. ``register_mcp``'s
own wiring is exercised end to end by ``tests/tool/test_mcp_adapter.py``,
mocked at the ``ClientSession`` boundary.
"""

from __future__ import annotations

from tool.registry import ToolRegistry
from tool.tools import markdown, pdf

from shared.types import ToolDefinition


async def _echo(**kwargs: object) -> dict[str, object]:
    return {"echo": kwargs}


async def _boom(**kwargs: object) -> object:
    raise ValueError("handler blew up")


def _make_definition(name: str = "echo") -> ToolDefinition:
    return ToolDefinition(name=name, description="Echoes its arguments.")


def test_register_local_makes_tool_visible_in_get_tools() -> None:
    registry = ToolRegistry()
    registry.register_local(_make_definition(), _echo)

    names = [tool.name for tool in registry.get_tools()]

    assert names == ["echo"]


async def test_call_tool_invokes_the_registered_handler() -> None:
    registry = ToolRegistry()
    registry.register_local(_make_definition(), _echo)

    result = await registry.call_tool("echo", {"message": "hi"})

    assert result.tool_name == "echo"
    assert result.content == {"echo": {"message": "hi"}}
    assert result.is_error is False


async def test_call_tool_returns_is_error_for_unknown_tool_name() -> None:
    registry = ToolRegistry()

    result = await registry.call_tool("does_not_exist", {})

    assert result.is_error is True
    assert "does_not_exist" in str(result.content)


async def test_call_tool_returns_is_error_when_handler_raises() -> None:
    registry = ToolRegistry()
    registry.register_local(_make_definition(name="boom"), _boom)

    result = await registry.call_tool("boom", {})

    assert result.tool_name == "boom"
    assert result.is_error is True
    assert "handler blew up" in str(result.content)


def test_register_local_replaces_existing_tool_with_same_name() -> None:
    registry = ToolRegistry()
    registry.register_local(_make_definition(), _echo)
    registry.register_local(_make_definition(), _echo)  # same name - should replace

    assert len(registry.get_tools()) == 1


async def test_register_local_makes_a_real_tool_file_callable() -> None:
    registry = ToolRegistry()
    registry.register_local(pdf.DEFINITION, pdf.extract_pdf)
    registry.register_local(markdown.DEFINITION, markdown.extract_markdown)

    names = {tool.name for tool in registry.get_tools()}
    assert names == {"extract_pdf", "extract_markdown"}

    result = await registry.call_tool("extract_markdown", {"path": "/nonexistent"})
    assert result.is_error is True  # handler ran for real and failed on a missing file
