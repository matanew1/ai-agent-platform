"""HTTP routes for caller-scoped customizable agents."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from rag.service import RAGService

from agents.api.schemas import (
    AgentResponse,
    ChatRequest,
    ChatResponse,
    CreateAgentRequest,
    IngestDocumentRequest,
    IngestDocumentResponse,
    UpdateAgentRequest,
)
from agents.runtime import AgentRuntimeFactory
from agents.service import AgentDefinitionService
from shared.documents import extract_document_text
from shared.types import AgentDefinition

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_response(definition: AgentDefinition) -> AgentResponse:
    """Build the public response without exposing the internal owner id."""
    return AgentResponse.model_validate(definition, from_attributes=True)


async def _owned_definition(
    request: Request, owner_id: str, agent_id: str
) -> AgentDefinition:
    """Load an agent only when it belongs to the supplied owner id."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    definition = await definitions.get(owner_id, agent_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return definition


def _scoped_session_id(owner_id: str, agent_id: str, session_id: str) -> str:
    """Namespace memory and locks so agents cannot share a client session id."""
    return f"{owner_id}:{agent_id}:{session_id}"


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: CreateAgentRequest, request: Request) -> AgentResponse:
    """Create an agent definition scoped to the caller-supplied owner id."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    try:
        data = payload.model_dump()
        owner_id = data.pop("owner_id")
        definition = await definitions.create(owner_id=owner_id, **data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _agent_response(definition)


@router.get("", response_model=list[AgentResponse])
async def list_agents(request: Request, owner_id: str) -> list[AgentResponse]:
    """List agent definitions for the supplied owner id."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    return [_agent_response(definition) for definition in await definitions.list(owner_id)]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, request: Request, owner_id: str) -> AgentResponse:
    """Get one agent definition for the supplied owner id."""
    definition = await _owned_definition(request, owner_id, agent_id)
    return _agent_response(definition)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str, payload: UpdateAgentRequest, request: Request, owner_id: str
) -> AgentResponse:
    """Update an owned definition and advance its configuration version."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    try:
        definition = await definitions.update(
            owner_id, agent_id, **payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return _agent_response(definition)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, request: Request, owner_id: str) -> None:
    """Delete an agent definition belonging to the supplied owner id."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    if not await definitions.delete(owner_id, agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")


@router.post("/{agent_id}/documents", response_model=IngestDocumentResponse)
async def ingest_agent_document(
    agent_id: str,
    payload: IngestDocumentRequest,
    request: Request,
    owner_id: str,
) -> IngestDocumentResponse:
    """Index a text document that only this owner and agent can retrieve."""
    await _owned_definition(request, owner_id, agent_id)
    rag_service: RAGService = request.app.state.rag_service
    scoped_source_id = f"{owner_id}:{agent_id}:{payload.source_id}"
    chunks_indexed = await rag_service.ingest_document(
        text=payload.text,
        source_id=scoped_source_id,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        metadata={"owner_id": owner_id, "agent_id": agent_id},
    )
    return IngestDocumentResponse(source_id=payload.source_id, chunks_indexed=chunks_indexed)


@router.post("/{agent_id}/documents/file", response_model=IngestDocumentResponse)
async def ingest_agent_file(
    agent_id: str,
    request: Request,
    owner_id: str,
    file: Annotated[UploadFile, File()],
    source_id: Annotated[str | None, Form()] = None,
) -> IngestDocumentResponse:
    """Extract and index a TXT, PDF, or DOCX file for one agent only."""
    await _owned_definition(request, owner_id, agent_id)
    filename = file.filename or "upload"
    try:
        text = await asyncio.to_thread(extract_document_text, filename, await file.read())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    document_source_id = source_id or filename
    rag_service: RAGService = request.app.state.rag_service
    chunks_indexed = await rag_service.ingest_document(
        text=text,
        source_id=f"{owner_id}:{agent_id}:{document_source_id}",
        metadata={"owner_id": owner_id, "agent_id": agent_id},
    )
    return IngestDocumentResponse(source_id=document_source_id, chunks_indexed=chunks_indexed)


@router.post("/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
    agent_id: str, payload: ChatRequest, request: Request, owner_id: str
) -> ChatResponse:
    """Run a chat turn against the caller's configured agent runtime."""
    definition = await _owned_definition(request, owner_id, agent_id)
    factory: AgentRuntimeFactory = request.app.state.agent_runtime_factory
    result = await factory.get(definition).run(
        session_id=_scoped_session_id(owner_id, agent_id, payload.session_id),
        message=payload.message,
        tools=definition.allowed_tools,
    )
    return ChatResponse(
        session_id=payload.session_id,
        message=result.answer,
        execution_time_seconds=result.execution_time_seconds,
        tools_invoked=result.tools_invoked,
        chunks_retrieved=result.chunks_retrieved,
    )


@router.post("/{agent_id}/chat/stream")
async def stream_with_agent(
    agent_id: str, payload: ChatRequest, request: Request, owner_id: str
) -> StreamingResponse:
    """Stream a response from the caller's configured agent runtime."""
    definition = await _owned_definition(request, owner_id, agent_id)
    factory: AgentRuntimeFactory = request.app.state.agent_runtime_factory
    metadata, stream = await factory.get(definition).run_stream(
        session_id=_scoped_session_id(owner_id, agent_id, payload.session_id),
        message=payload.message,
        tools=definition.allowed_tools,
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
