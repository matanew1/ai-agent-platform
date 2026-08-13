"""Format shared data shapes for inclusion in LLM prompts."""

from __future__ import annotations

import json
import re

from shared.types import ChatMessage, Chunk, ToolDefinition, ToolResult

# A past assistant turn's saved `content` can contain a real
# "...download it from /artifacts/document-3.pdf" sentence (the model was
# told to state one, see GENERATE_ANSWER_PROMPT_TEMPLATE). Replaying that
# verbatim into a later prompt via format_history gives the model a
# copyable "/artifacts/document-N.pdf" precedent it can pattern-complete
# into a *new*, never-generated filename on a turn where no file-generation
# tool actually ran - confirmed live (a "what have changed?" turn that only
# called rag_search still asserted a "document-4.pdf" download link, which
# 404'd because that file was never created). Neutralizing the link in
# history removes the pattern to extrapolate from; this turn's *own*
# artifacts still reach the model correctly via format_tool_results, which
# is untouched.
_HISTORICAL_ARTIFACT_LINK = re.compile(r"/artifacts/\S+")


def format_history(history: list[ChatMessage]) -> str:
    if not history:
        return "(none)"
    return "\n".join(
        f"{turn.role}: {_HISTORICAL_ARTIFACT_LINK.sub('[link omitted from history]', turn.content)}"
        for turn in history
    )


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


def format_attachments(attachments: list[tuple[str, str]]) -> str:
    """Render files attached to a single chat turn - (filename, extracted text) pairs."""
    if not attachments:
        return "(none)"
    return "\n".join(f"- {filename}:\n{text}" for filename, text in attachments)
