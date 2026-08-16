"""HTTP endpoint for listing registered tools.

Deliberately read-only: there is no ``POST /tools/{name}`` here. A prior
version exposed one, letting any authenticated user invoke any registered
tool - including ``fetch``, which ``.claude/rules/tool-conventions.md``
already treats as a prompt-injection/SSRF risk when reached through the
agent's own LLM tool-selection path - with arbitrary arguments and no
per-agent ``allowed_tools`` check at all. That bypassed the one thing
gating tool access everywhere else in the app (``agent.allowed_tools``,
enforced in ``graph.graph._execute_tools``), and nothing in the web
client ever called it (only ``GET /tools``, to render the read-only Tool
Registry screen). Removed rather than authorized, per this module's own
"don't keep a capability just in case" precedent (see
``tool-conventions.md``'s removed ``tool_overrides`` case study) - add it
back only alongside a real per-agent authorization check if a genuine
caller shows up.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from tool.service import ToolService

from shared.types import ToolDefinition

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolDefinition])
async def list_tools(request: Request) -> list[ToolDefinition]:
    """List tools currently registered in the application."""
    tool_registry: ToolService = request.app.state.tool_registry
    return tool_registry.get_tools()
