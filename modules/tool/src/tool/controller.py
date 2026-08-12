"""HTTP endpoints for listing and invoking local tools."""

from __future__ import annotations

from artifact.service import ArtifactService
from fastapi import APIRouter, Request
from tool.schemas import ToolCallRequest
from tool.service import ToolService

from shared.auth import AuthenticatedUser
from shared.types import ArtifactReference, ToolDefinition, ToolResult

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolDefinition])
async def list_tools(request: Request) -> list[ToolDefinition]:
    """List tools currently registered in the application."""
    tool_registry: ToolService = request.app.state.tool_registry
    return tool_registry.get_tools()


@router.post("/{name}", response_model=ToolResult)
async def call_tool(name: str, payload: ToolCallRequest, request: Request) -> ToolResult:
    """Run a registered tool with JSON arguments."""
    tool_registry: ToolService = request.app.state.tool_registry
    result = await tool_registry.call_tool(name, payload.arguments)
    artifact = _artifact_reference(result)
    current_user: AuthenticatedUser | None = getattr(request.state, "current_user", None)
    if artifact is not None and current_user is not None:
        artifact_service: ArtifactService = request.app.state.artifact_service
        await artifact_service.grant(current_user.id, [artifact])
    return result


def _artifact_reference(result: ToolResult) -> ArtifactReference | None:
    if result.is_error or not isinstance(result.content, dict):
        return None
    filename = result.content.get("filename")
    download_url = result.content.get("download_url")
    if not isinstance(filename, str) or not isinstance(download_url, str):
        return None
    return ArtifactReference(filename=filename, download_url=download_url)
