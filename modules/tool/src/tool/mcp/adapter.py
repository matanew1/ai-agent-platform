"""Adapt one external MCP server's tools into RegisteredTools.

Purely about talking to the server - it doesn't know what a ``ToolRegistry``
is. ``ToolRegistry.register_mcp`` (see ``tool/registry.py``) is what takes
the list this returns and actually stores it.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters, Tool, stdio_client
from mcp.types import TextContent

from shared.types import ToolDefinition
from tool.registry import RegisteredTool

logger = logging.getLogger(__name__)


class McpServerAdapter:
    """One live connection to an external MCP server.

    Construct directly with an already-initialized ``ClientSession`` (this
    is what's unit-tested, against a fake session - see
    ``tests/tool/test_mcp_adapter.py``), or via ``connect`` for the real
    stdio connection (I/O, exercised live rather than unit-tested, the
    same treatment ``.claude/rules/testing.md`` gives every other adapter).
    """

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    @classmethod
    async def connect(
        cls, server_params: StdioServerParameters, exit_stack: AsyncExitStack
    ) -> McpServerAdapter:
        """Open a stdio connection to an MCP server and initialize it.

        Entered into ``exit_stack`` rather than closed here, so the
        connection - and every tool later registered from it - stays
        usable for the process's lifetime; ``exit_stack`` is owned and
        closed by the caller at shutdown (see ``app/lifespan.py``).

        Args:
            server_params: Which process to spawn and how.
            exit_stack: Keeps the connection open past this call.
        """
        read_stream, write_stream = await exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return cls(session)

    async def list_tools(self) -> list[RegisteredTool]:
        """List this server's tools, each adapted into a ``RegisteredTool``."""
        response = await self._session.list_tools()
        return [self._adapt(remote_tool) for remote_tool in response.tools]

    def _adapt(self, remote_tool: Tool) -> RegisteredTool:
        """Build a RegisteredTool that calls ``remote_tool`` through this session.

        Arguments are passed through exactly as the agent supplied them. A
        config layer for rewriting them per tool was built here and removed
        again once its only user went away - see
        ``.claude/rules/tool-conventions.md`` on what that involved, and why
        the agent choosing per call is the better default anyway.
        """

        async def handler(**arguments: object) -> object:
            result = await self._session.call_tool(remote_tool.name, arguments)
            texts = [
                block.text if isinstance(block, TextContent) else f"<{block.type}>"
                for block in result.content
            ]
            content = texts[0] if len(texts) == 1 else texts
            if result.is_error:
                # Raise rather than returning error content directly -
                # ToolRegistry.call_tool already turns a raised exception
                # into ToolResult(is_error=True, ...), so this reuses that
                # path instead of inventing a second one.
                raise RuntimeError(str(content))
            return content

        return RegisteredTool(
            definition=ToolDefinition(
                name=remote_tool.name,
                description=remote_tool.description or "",
                parameters=remote_tool.input_schema or {},
            ),
            handler=handler,
        )
