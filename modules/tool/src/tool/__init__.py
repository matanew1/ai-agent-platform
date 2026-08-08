"""Agent-callable tool registry.

In-process tools live in ``tool.tools`` (plain functions, no decorator)
and external MCP-server adapters live in ``tool.mcp``. Both are wired into
one ``ToolRegistry`` explicitly, via ``register_local``/``register_mcp``
(see ``app/lifespan.py``).
"""

from tool.registry import ToolRegistry

__all__ = ["ToolRegistry"]
