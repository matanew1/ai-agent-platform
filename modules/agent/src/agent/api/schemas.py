"""Pydantic request/response models for the agent module's HTTP surface.

Kept separate from ``agent.internal.graph.AgentState`` (the internal LangGraph
state) and from any future internal domain model - the API contract and
the internal representation are allowed to change independently. See
``.claude/rules/api-conventions.md``.
"""

from __future__ import annotations

from pydantic import BaseModel


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

    Attributes:
        session_id: Echoes the request's session id.
        message: The agent's reply.
    """

    session_id: str
    message: str
