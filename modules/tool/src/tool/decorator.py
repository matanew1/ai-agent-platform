"""``@mcp_tool``: turn a plain async function into a local, agent-callable tool.

    @mcp_tool(name="extract_pdf", description="Extract text from a PDF.")
    async def extract_pdf(path: str) -> dict:
        ...

Decorated functions accumulate in ``_LOCAL_TOOLS`` at import time (see
``tool/tools/`` for the actual tools, one file each). Call
``register_local_tools`` once, at startup, with a live registry to add them
all - see ``app/lifespan.py``. Adding a new local tool never requires
touching this file (open/closed): just decorate a new function.
"""

from __future__ import annotations

from collections.abc import Callable

from shared.types import ToolDefinition
from tool.registry import RegisteredTool, ToolHandler, ToolRegistry

_LOCAL_TOOLS: list[RegisteredTool] = []


def mcp_tool(
    name: str,
    description: str,
    parameters: dict[str, object] | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Mark an async function as a local, agent-callable tool.

    Args:
        name: Unique, action-oriented tool name (e.g. ``extract_pdf``).
        description: What the tool does and when to use it - this is what
            the LLM uses to decide whether to call it, so keep it complete.
            See ``.claude/rules/tool-conventions.md``.
        parameters: JSON-schema-shaped description of the function's
            arguments. Defaults to an empty schema.

    Returns:
        A decorator that registers the function and returns it unchanged.
    """

    def decorator(func: ToolHandler) -> ToolHandler:
        definition = ToolDefinition(name=name, description=description, parameters=parameters or {})
        _LOCAL_TOOLS.append(RegisteredTool(definition=definition, handler=func))
        return func

    return decorator


def register_local_tools(registry: ToolRegistry) -> None:
    """Register every ``@mcp_tool``-declared function into a registry.

    Args:
        registry: Registry to register into.
    """
    for tool in _LOCAL_TOOLS:
        registry.register(tool)
