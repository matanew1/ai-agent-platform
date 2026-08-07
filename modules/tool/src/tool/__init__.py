"""Local tool registry: agent-callable tools, unified behind one lookup/
execution surface that the agent depends on through its ``ToolRegistry``
port.

The directory is ``modules/tool/`` and the importable package is ``tool``.
Tool definitions produced here mirror the Model Context Protocol's tool
shape (``ToolDefinition``/``ToolResult``, see ``shared/types.py``), though
this module only backs them with local Python functions today - no
external MCP server integration. See ``.claude/rules/tool-conventions.md``.
"""

from tool.registry import ToolRegistry

__all__ = ["ToolRegistry"]
