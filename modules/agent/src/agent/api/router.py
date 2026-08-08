"""Private admin/test routes for the core agent workflow."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agent.api.schemas import ChatRequest, ChatResponse
from agent.service import AgentService

router = APIRouter(prefix="/admin/agent", tags=["[ADMIN ONLY] Agent"])


@router.post("/chat", response_model=ChatResponse, summary="[ADMIN ONLY] Run core agent chat")
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Run the core agent directly for private testing and diagnostics."""
    agent_service: AgentService = request.app.state.agent_service
    result = await agent_service.run(
        session_id=payload.session_id,
        message=payload.message,
        tools=payload.tools,
    )
    return ChatResponse(
        session_id=payload.session_id,
        message=result.answer,
        execution_time_seconds=result.execution_time_seconds,
        tools_invoked=result.tools_invoked,
        chunks_retrieved=result.chunks_retrieved,
    )


@router.post("/chat/stream", summary="[ADMIN ONLY] Stream core agent chat")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Stream a direct core-agent response for private testing and diagnostics."""
    agent_service: AgentService = request.app.state.agent_service
    metadata, stream = await agent_service.run_stream(
        session_id=payload.session_id,
        message=payload.message,
        tools=payload.tools,
    )
    return StreamingResponse(
        stream,
        media_type="text/plain",
        headers={
            "X-Tools-Invoked": json.dumps(metadata.tools_invoked),
            "X-Chunks-Retrieved": str(metadata.chunks_retrieved),
            "X-Prep-Time-Seconds": f"{metadata.prep_time_seconds:.3f}",
        },
    )
