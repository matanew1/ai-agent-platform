"""The tool registry: its data structure, and how tools get looked up and run.

Local and external MCP tools share one lookup/execution surface.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Self

from mcp import StdioServerParameters

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


class ToolService:
    """Tool discovery and execution, holding local and external MCP tools by name.

    No ``Protocol`` port: this is the only implementation, and every
    consumer (``graph.graph``, ``agent.service``, ``agent.service``)
    imports it directly - see ``.claude/rules/architecture.md``'s
    "Avoiding over-engineering".
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register_local(self, definition: ToolDefinition, handler: ToolHandler) -> Self:
        """Register one in-process tool - see ``tool/tools/*.py``.

        Plain functions, no decorator: a tool file just defines a
        module-level ``DEFINITION`` and an async handler; this is the one
        call that makes it agent-callable, called once per tool from
        ``app/lifespan.py`` (e.g. ``registry.register_local(pdf.DEFINITION,
        pdf.extract_pdf)``) - the same explicit, no-magic shape as
        ``register_mcp`` below, just without the connection step a local
        tool doesn't need. Returns this registry so local registrations can
        be chained at the composition root.

        Args:
            definition: Name/description/parameters, as exposed to the agent.
            handler: Async callable that executes the tool given its arguments.
        """
        self._tools[definition.name] = RegisteredTool(definition=definition, handler=handler)
        logger.debug("Registered tool %r", definition.name)
        return self

    async def register_mcp(
        self, server_params: StdioServerParameters, exit_stack: AsyncExitStack
    ) -> Self:
        """Connect to an external MCP server and register every tool it
        exposes into this registry. Returns this registry after registration
        so callers can continue a fluent build after awaiting the I/O step.

        ``McpServerAdapter`` (imported lazily - ``tool.tools.mcp.adapter`` imports
        this class, so importing it back at module level here would be a
        circular import) does the actual connecting and adapting; this
        registry does the registering, e.g.
        ``registry.register_mcp(server_params, exit_stack)`` from
        ``app/lifespan.py`` - see ``tool.tools.mcp.config.load_servers`` for
        where ``server_params`` comes from.

        Args:
            server_params: Which process to spawn and how (command, args,
                env).
            exit_stack: Holds the connection open past this call - see
                ``McpServerAdapter.connect``'s docstring for why.
        """
        from tool.tools.mcp.adapter import McpServerAdapter

        adapter = await McpServerAdapter.connect(server_params, exit_stack)
        tools = await adapter.list_tools()
        for tool in tools:
            self._tools[tool.definition.name] = tool
        logger.info(
            "Registered %d tool(s) from MCP server command=%r args=%r",
            len(tools),
            server_params.command,
            server_params.args,
        )
        return self

    def get_tools(self) -> list[ToolDefinition]:
        """List tools currently available to the agent."""
        return [tool.definition for tool in self._tools.values()]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        """Execute a registered tool by name.

        Never raises: an unknown name or a failing handler both come back
        as ``ToolResult(is_error=True, ...)`` - the caller is typically an
        LLM's freeform tool choice, not a hardcoded call.

        Args:
            name: Tool name, as returned by ``get_tools``.
            arguments: Arguments matching the tool's declared parameters.

        Returns:
            The tool's result.
        """
        # Keys, not values, even at DEBUG - an argument can be a file's raw
        # content, a credential, or other sensitive data (see
        # infrastructure.llm.ollama's generate() for the same policy).
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
