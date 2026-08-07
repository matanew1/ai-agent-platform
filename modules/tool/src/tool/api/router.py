"""HTTP endpoints for listing and invoking local tools."""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.types import ToolDefinition, ToolResult
from tool.api.schemas import ToolCallRequest
from tool.registry import ToolRegistry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolDefinition])
async def list_tools(request: Request) -> list[ToolDefinition]:
    """List tools currently registered in the application."""
    tool_registry: ToolRegistry = request.app.state.tool_registry
    return tool_registry.get_tools()


@router.post("/{name}", response_model=ToolResult)
async def call_tool(name: str, payload: ToolCallRequest, request: Request) -> ToolResult:
    """Run a registered tool with JSON arguments."""
    tool_registry: ToolRegistry = request.app.state.tool_registry
    return await tool_registry.call_tool(name, payload.arguments)
