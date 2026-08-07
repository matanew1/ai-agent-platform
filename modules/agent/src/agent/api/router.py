"""HTTP surface for the agent module: ``POST /chat`` and ``POST /chat/stream``.

Mounted onto the FastAPI app from ``app/main.py`` via
``app.include_router(agent_router)``. This file only imports from
``fastapi`` (third-party) and the agent module's own code - never from
``app``, which would invert the one allowed direction (``app -> agent``,
see ``.claude/rules/architecture.md``). It reaches the ``AgentService``
built at startup through the generic ``request.app.state`` FastAPI gives
every handler, not through an import of the ``app`` package.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agent.api.schemas import ChatRequest, ChatResponse
from agent.service import AgentService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Send a message to the agent and get its reply.

    Args:
        payload: The chat request.
        request: Used to reach the ``AgentService`` built at startup by
            ``app/lifespan.py``'s ``lifespan`` and attached to ``app.state``.

    Returns:
        The agent's reply, tied to the same session id.
    """
    logger.debug("POST /chat session_id=%r", payload.session_id)
    agent_service: AgentService = request.app.state.agent_service
    reply = await agent_service.run(session_id=payload.session_id, message=payload.message)
    return ChatResponse(session_id=payload.session_id, message=reply)


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Send a message to the agent and stream its reply as it's generated.

    A separate endpoint rather than a flag on ``POST /chat`` - see
    ``.claude/rules/api-conventions.md``. Same request body as ``POST
    /chat``; the response is the answer's raw text, sent chunk-by-chunk as
    the LLM generates it (``media_type="text/plain"``) instead of waiting
    for the full answer and returning JSON. Reduces perceived latency
    (time-to-first-token), not total generation time - everything before
    the final answer (planning, retrieval, tool calls) still has to finish
    first, same as ``POST /chat``.

    Args:
        payload: The chat request.
        request: Used to reach the ``AgentService`` built at startup by
            ``app/lifespan.py``'s ``lifespan`` and attached to ``app.state``.

    Returns:
        A streaming plain-text response of the agent's reply.
    """
    logger.debug("POST /chat/stream session_id=%r", payload.session_id)
    agent_service: AgentService = request.app.state.agent_service
    return StreamingResponse(
        agent_service.run_stream(session_id=payload.session_id, message=payload.message),
        media_type="text/plain",
    )
