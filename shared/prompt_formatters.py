"""Format shared data shapes for inclusion in LLM prompts."""

from __future__ import annotations

import json

from shared.types import ChatMessage, Chunk, ToolDefinition, ToolResult


def format_history(history: list[ChatMessage]) -> str:
    return "\n".join(f"{turn.role}: {turn.content}" for turn in history) if history else "(none)"


def format_context(context: list[Chunk]) -> str:
    return "\n".join(f"- {chunk.text}" for chunk in context) if context else "(none)"


def format_tools(tools: list[ToolDefinition]) -> str:
    if not tools:
        return "(no tools available)"
    return "\n".join(
        f"- {tool.name}: {tool.description} (parameters: {json.dumps(tool.parameters)})"
        for tool in tools
    )


def format_tool_results(tool_results: list[ToolResult]) -> str:
    if not tool_results:
        return "(none)"
    return "\n".join(
        f"- {result.tool_name}{' (failed)' if result.is_error else ''}: {result.content!r}"
        for result in tool_results
    )
