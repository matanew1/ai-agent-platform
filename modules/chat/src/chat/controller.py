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
import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import PurePath

from agent.service import AgentService
from artifact.service import ArtifactService
from authentication.controller import current_user
from chat.schemas import ChatRequest
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from shared.auth import AuthenticatedUser
from shared.documents import extract_document_text

router = APIRouter(prefix="/agents", tags=["agents"])


async def _stream_until_disconnect(
    request: Request, stream: AsyncIterator[str]
) -> AsyncIterator[str]:
    """Yield a response stream until its browser client disconnects.

    Closing the source generator cancels an in-flight provider stream and
    releases the chat service's per-session lock instead of continuing an
    answer the browser has explicitly stopped.
    """
    iterator = stream.__aiter__()
    try:
        while not await request.is_disconnected():
            try:
                yield await anext(iterator)
            except StopAsyncIteration:
                return
    finally:
        close_stream = getattr(iterator, "aclose", None)
        if close_stream is not None:
            await close_stream()


def _attachment_source_id(agent_id: str, filename: str, content: bytes) -> str:
    """Create a stable, displayable source ID without trusting client ownership."""
    safe_filename = PurePath(filename.replace("\\", "/")).name
    safe_filename = "".join(character for character in safe_filename if character.isprintable())
    safe_filename = safe_filename.strip(" .")[:120] or "upload"
    digest = hashlib.sha256(content).hexdigest()[:16]
    return f"chat/{agent_id}/{digest}-{safe_filename}"


@router.post("/{agent_id}/chat/stream")
@current_user
async def stream_with_agent(
    agent_id: str,
    payload: ChatRequest,
    request: Request,
    current_user: AuthenticatedUser,
) -> StreamingResponse:
    """Stream a response from the caller's configured agent runtime.

    ``payload.files``, if any, are extracted, indexed in the authenticated
    user's document library, and folded into this turn's answer prompt.
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
    document_library = request.app.state.rag_service
    indexed_documents: list[dict[str, object]] = []
    for (filename, content), text in zip(decoded_attachments, attachment_texts, strict=True):
        source_id = _attachment_source_id(agent_id, filename, content)
        chunks_indexed = await document_library.ingest_document(
            text=text,
            source_id=f"{current_user.id}:{source_id}",
            metadata={"owner_id": current_user.id, "agent_id": agent_id},
        )
        indexed_documents.append({"source_id": source_id, "chunks_indexed": chunks_indexed})
    chat_service = request.app.state.chat_service_factory(agent=definition)
    metadata, stream = await chat_service.run_stream(
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
        _stream_until_disconnect(request, stream),
        media_type="text/plain",
        headers={
            "X-Tools-Invoked": json.dumps(metadata.tools_invoked),
            "X-Chunks-Retrieved": str(metadata.chunks_retrieved),
            "X-Prep-Time-Seconds": f"{metadata.prep_time_seconds:.3f}",
            "X-Indexed-Documents": json.dumps(indexed_documents),
            "X-Artifacts": json.dumps(
                [artifact.model_dump(mode="json") for artifact in metadata.artifacts]
            ),
            "X-Retrieved-Sources": json.dumps(
                [source.model_dump(mode="json") for source in metadata.sources]
            ),
        },
    )
