"""In-process tools implemented and run by this application.

Each file here defines a module-level ``DEFINITION`` (``ToolDefinition``)
and a plain async handler function - nothing registers itself. A tool
becomes agent-callable only when something calls
``ToolRegistry.register_local(DEFINITION, handler)`` - see
``app/lifespan.py``, which does this once per tool at startup, the same
explicit, no-magic pattern ``ToolRegistry.register_mcp`` uses for external
MCP servers (see ``tool/mcp/``).
"""
