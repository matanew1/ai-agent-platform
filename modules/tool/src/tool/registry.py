"""The tool registry: its data structure, and how tools get looked up and run.

Local tools (declared with ``@mcp_tool``, see ``decorator.py``) sit behind
one lookup/execution surface - the agent only ever sees this registry,
never a local function directly. See ``.claude/rules/tool-conventions.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from shared.types import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[object]]


@dataclass
class RegisteredTool:
    """A tool's definition paired with the callable that executes it.

    Attributes:
        definition: Name/description/parameters, as exposed to the agent.
        handler: Async callable that executes the tool given its arguments.
    """

    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    """Registry that satisfies the agent's ``agent.internal.ports.ToolRegistry`` port.

    Holds every ``@mcp_tool``-declared local tool, keyed by name. Named the
    same as the port it implements - the two are distinguished by module
    path, not name: this is the concrete implementation,
    ``agent.internal.ports.ToolRegistry`` is the ``Protocol`` it
    structurally satisfies.
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        """Add a tool to the registry, replacing any existing tool with the
        same name.

        Args:
            tool: Tool definition plus its execution handler.
        """
        self._tools[tool.definition.name] = tool
        logger.debug("Registered tool %r", tool.definition.name)

    def get_tools(self) -> list[ToolDefinition]:
        """List tools currently available to the agent."""
        return [tool.definition for tool in self._tools.values()]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        """Execute a registered tool by name.

        Never raises: an unknown name or a failing handler both come back
        as ``ToolResult(is_error=True, ...)`` rather than an exception, per
        ``agent.internal.ports.ToolRegistry.call_tool``'s contract - the caller is
        typically an LLM's freeform tool choice, not a hardcoded call.

        Args:
            name: Tool name, as returned by ``get_tools``.
            arguments: Arguments matching the tool's declared parameters.

        Returns:
            The tool's result.
        """
        # Keys, not values, even at DEBUG - an argument can be a file's raw
        # content, a credential, or other sensitive data (see
        # infrastructure/llm.py's generate() for the same policy).
        logger.info("call_tool name=%r", name)
        logger.debug("call_tool name=%r argument_keys=%s", name, list(arguments.keys()))
        tool = self._tools.get(name)
        if tool is None:
            logger.warning("call_tool: no tool registered under name %r", name)
            return ToolResult(
                tool_name=name,
                content=f"No tool registered under name {name!r}.",
                is_error=True,
            )
        try:
            content = await tool.handler(**arguments)
        except Exception as exc:
            logger.warning("call_tool: %r handler raised: %s", name, exc)
            return ToolResult(tool_name=name, content=str(exc), is_error=True)
        return ToolResult(tool_name=name, content=content)
