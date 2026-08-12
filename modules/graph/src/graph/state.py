"""State passed between nodes in the agent workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.types import ChatMessage, Chunk, ToolResult


class AgentState(BaseModel):
    """State passed between nodes in the workflow below.

    Each node reads what it needs from this state and returns a partial
    update; LangGraph merges the update back in.

    Attributes:
        session_id: Conversation/session identifier.
        input: The user's latest message.
        history: Prior turns in this conversation, oldest first.
        attachments: Extracted files attached to this turn.
        allowed_tools: Tool names execute_tools may consider this turn.
            Empty (the default) means every registered tool is available -
            see ``graph._execute_tools``. A name not in the registry just
            means one less usable tool, the same as an unknown name
            reaching ``ToolService.call_tool`` - not an error.
        context: Chunks retrieved by the retrieve_context node.
        tool_results: Results from tools run by the execute_tools node.
    """

    session_id: str
    input: str
    history: list[ChatMessage] = Field(default_factory=list)
    attachments: list[tuple[str, str]] = Field(default_factory=list)
    allowed_tools: list[str] | None = None
    context: list[Chunk] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)


__all__ = ["AgentState"]
