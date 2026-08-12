"""HTTP route for streaming chat with a configured agent.

Shares the ``/agents`` prefix with ``agent.controller``'s router but is
mounted as its own ``APIRouter`` from ``app/main.py`` - turn *execution*
(this module) is a distinct concern from turn *configuration*
(``agent.service``) and *persisted history* (``agent.controller``'s
session routes), even though all three sit under the same public path.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json

from agent.service import AgentService
from artifact.service import ArtifactService
from authentication.controller import CurrentUser
from chat.factory import AgentRuntimeFactory
from chat.schemas import ChatRequest
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from shared.documents import extract_document_text

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/{agent_id}/chat/stream")
async def stream_with_agent(
    agent_id: str,
    payload: ChatRequest,
    request: Request,
    current_user: CurrentUser,
) -> StreamingResponse:
    """Stream a response from the caller's configured agent runtime.

    ``payload.files``, if any, are extracted and folded into this turn's
    answer only (see ``ChatService.run_stream``'s ``attachments``) - not
    persisted. For documents that should be searchable in future turns,
    use ``rag.controller``'s ingestion routes instead.
    """
    definitions: AgentService = request.app.state.agent_service
    definition = await definitions.get(current_user.id, agent_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    decoded_attachments: list[tuple[str, bytes]] = []
    for attachment in payload.files:
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except binascii.Error as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{attachment.filename!r}: invalid base64 content ({exc}).",
            ) from exc
        decoded_attachments.append((attachment.filename, content))
    try:
        attachment_texts = await asyncio.gather(
            *(
                asyncio.to_thread(extract_document_text, filename, content)
                for filename, content in decoded_attachments
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    attachments = [
        (filename, text)
        for (filename, _content), text in zip(decoded_attachments, attachment_texts, strict=True)
    ]
    factory: AgentRuntimeFactory = request.app.state.agent_runtime_factory
    metadata, stream = await factory.get(definition).run_stream(
        session_id=f"{current_user.id}:{agent_id}:{payload.session_id}",
        message=payload.message,
        tools=definition.allowed_tools,
        attachments=attachments,
    )
    artifact_service: ArtifactService = request.app.state.artifact_service
    try:
        await artifact_service.grant(current_user.id, metadata.artifacts)
    except BaseException:
        # run_stream's async generator owns the per-session lock. If the
        # ownership manifest cannot be persisted before the response starts,
        # close it explicitly so that lock cannot leak.
        close_stream = getattr(stream, "aclose", None)
        if close_stream is not None:
            await close_stream()
        raise
    return StreamingResponse(
        stream,
        media_type="text/plain",
        headers={
            "X-Tools-Invoked": json.dumps(metadata.tools_invoked),
            "X-Chunks-Retrieved": str(metadata.chunks_retrieved),
            "X-Prep-Time-Seconds": f"{metadata.prep_time_seconds:.3f}",
            "X-Artifacts": json.dumps(
                [artifact.model_dump(mode="json") for artifact in metadata.artifacts]
            ),
        },
    )
