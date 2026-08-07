"""Unit tests for tool.registry.ToolRegistry.

ToolRegistry has no external dependency, so these are real (not stub)
assertions.
"""

from __future__ import annotations

from tool.registry import RegisteredTool, ToolRegistry

from shared.types import ToolDefinition


async def _echo(**kwargs: object) -> dict[str, object]:
    return {"echo": kwargs}


async def _boom(**kwargs: object) -> object:
    raise ValueError("handler blew up")


def _make_tool(name: str = "echo", handler=_echo) -> RegisteredTool:
    return RegisteredTool(
        definition=ToolDefinition(name=name, description="Echoes its arguments."),
        handler=handler,
    )


def test_register_makes_tool_visible_in_get_tools() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool())

    names = [tool.name for tool in registry.get_tools()]

    assert names == ["echo"]


async def test_call_tool_invokes_the_registered_handler() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool())

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
    registry.register(_make_tool(name="boom", handler=_boom))

    result = await registry.call_tool("boom", {})

    assert result.tool_name == "boom"
    assert result.is_error is True
    assert "handler blew up" in str(result.content)


def test_register_replaces_existing_tool_with_same_name() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool())
    registry.register(_make_tool())  # same name - should replace, not duplicate

    assert len(registry.get_tools()) == 1
