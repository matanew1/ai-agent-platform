"""Local, in-process tools, declared with ``@mcp_tool``.

Importing this package runs each tool module's decorators below, which
append every tool to ``tool.decorator._LOCAL_TOOLS``; call
``tool.decorator.register_local_tools(registry)`` with a live
registry to actually add them (see ``app/lifespan.py``). Add a new local
tool by adding a new file here and importing it below - nothing else
changes (open/closed: the registry and startup wiring don't know or care
how many local tools exist).
"""

from tool.tools import markdown, pdf  # noqa: F401 - import triggers @mcp_tool registration

__all__ = ["markdown", "pdf"]
