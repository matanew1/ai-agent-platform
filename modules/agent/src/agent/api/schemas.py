"""Pydantic request/response models for the agent module's HTTP surface.

Kept separate from ``agent.internal.graph.AgentState`` (the internal LangGraph
state) and from any future internal domain model - the API contract and
the internal representation are allowed to change independently. See
``.claude/rules/api-conventions.md``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for ``POST /chat``.

    Attributes:
        session_id: Client-chosen conversation identifier, used to resume
            agent memory across turns.
        message: The user's message.
    """

    session_id: str
    message: str


class ChatResponse(BaseModel):
    """Response body for ``POST /chat``.

    ``/chat/stream`` doesn't get this shape - it returns raw
    ``text/plain`` (see ``.claude/rules/api-conventions.md``), which has
    no room for structured fields alongside the answer, so these are
    non-streaming-only.

    Attributes:
        session_id: Echoes the request's session id.
        message: The agent's reply.
        execution_time_seconds: Wall-clock time for the whole turn -
            session lock wait, history load, the graph run, and the save
            back to memory. See ``agent.service.AgentTurnResult``.
        tools_invoked: Name of every tool called for this turn, in call
            order - including one that failed. Empty when none were
            needed.
        chunks_retrieved: How many RAG chunks backed this answer. ``0``
            covers both "retrieval found nothing" and "retrieval was
            skipped" - see ``agent.service.AgentTurnResult``.
    """

    session_id: str
    message: str
    execution_time_seconds: float
    tools_invoked: list[str] = Field(default_factory=list)
    chunks_retrieved: int = 0
