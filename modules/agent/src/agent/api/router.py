"""HTTP routes for authenticated-user-scoped customizable agents.

Three routers: ``router`` (``/agents``) for agent definitions and chat;
``documents_router`` (``/documents``) for an owner's document library; and
``models_router`` (``/models``) for provider-aware configuration options.
Documents are deliberately not nested under ``/agents/{agent_id}`` -
they belong to the authenticated user, not to one agent, and every agent
that user owns shares the same pool (see
``agent.runtime.OwnerScopedRetriever``). All three routers are mounted from
``app/main.py``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from agent.api.auth import CurrentUser
from agent.api.schemas import (
    AgentResponse,
    ChatFileAttachment,
    ChatRequest,
    CreateAgentRequest,
    DocumentResponse,
    IngestDocumentRequest,
    IngestDocumentResponse,
    ModelCatalogResponse,
    ModelOptionResponse,
    SessionResponse,
    TemperatureOptionsResponse,
    UpdateAgentRequest,
)
from agent.definitions import AgentDefinitionService
from agent.ports import DocumentLibrary, Memory, ModelCatalog
from agent.runtime import AgentRuntimeFactory
from shared.documents import extract_document_text
from shared.types import AgentDefinition, IndexedDocument, SessionCheckpoint

router = APIRouter(prefix="/agents", tags=["agents"])
documents_router = APIRouter(prefix="/documents", tags=["documents"])
models_router = APIRouter(prefix="/models", tags=["models"])


# --- Helpers -------------------------------------------------------------------


def _agent_response(definition: AgentDefinition) -> AgentResponse:
    """Build the public response without exposing the internal owner id."""
    return AgentResponse.model_validate(definition, from_attributes=True)


async def _owned_definition(request: Request, owner_id: str, agent_id: str) -> AgentDefinition:
    """Load an agent only when it belongs to the supplied owner id."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    definition = await definitions.get(owner_id, agent_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return definition


def _scoped_session_id(owner_id: str, agent_id: str, session_id: str) -> str:
    """Namespace memory and locks so agents cannot share a client session id."""
    return f"{owner_id}:{agent_id}:{session_id}"


async def _ingest(
    document_library: DocumentLibrary,
    *,
    text: str,
    source_id: str,
    owner_id: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> IngestDocumentResponse:
    """Ingest one document into an owner's document library."""
    chunks_indexed = await document_library.ingest_document(
        text=text,
        source_id=f"{owner_id}:{source_id}",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        metadata={"owner_id": owner_id},
    )
    return IngestDocumentResponse(source_id=source_id, chunks_indexed=chunks_indexed)


def _session_response(checkpoint: SessionCheckpoint, scoped_prefix: str) -> SessionResponse:
    """Remove the internal owner/agent prefix from a checkpoint response."""
    return SessionResponse(
        session_id=checkpoint.session_id.removeprefix(scoped_prefix),
        history=checkpoint.history,
        updated_at=checkpoint.updated_at,
    )


def _source_response(document: IndexedDocument, owner_id: str) -> DocumentResponse | None:
    """Translate a stored owner-prefixed source id back to its client id."""
    prefix = f"{owner_id}:"
    if not document.source_id.startswith(prefix):
        return None
    return DocumentResponse(
        source_id=document.source_id.removeprefix(prefix),
        chunks_indexed=document.chunks_indexed,
    )


async def _extract_uploaded_text(file: UploadFile) -> tuple[str, str]:
    """Read an uploaded file and extract its text. Returns (filename, text).

    Raises:
        HTTPException: 415, if the file type isn't supported (see
            ``shared.documents.extract_document_text``).
    """
    filename = file.filename or "upload"
    try:
        text = await asyncio.to_thread(extract_document_text, filename, await file.read())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    return filename, text


async def _extract_attachments(files: list[ChatFileAttachment]) -> list[tuple[str, str]]:
    """Decode and extract text from files attached to one chat turn.

    Ephemeral (see ``AgentService.run_stream``'s ``attachments`` parameter)
    - never ingested, never saved to history. Files are extracted
    concurrently since they're independent of each other.

    Raises:
        HTTPException: 422 for invalid base64; 415 for an unsupported file
            type (see ``shared.documents.extract_document_text``).
    """

    async def extract_one(attachment: ChatFileAttachment) -> tuple[str, str]:
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except binascii.Error as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{attachment.filename!r}: invalid base64 content ({exc}).",
            ) from exc
        try:
            text = await asyncio.to_thread(extract_document_text, attachment.filename, content)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
            ) from exc
        return attachment.filename, text

    return list(await asyncio.gather(*(extract_one(attachment) for attachment in files)))


# --- Model configuration ---------------------------------------------------------


@models_router.get("", response_model=ModelCatalogResponse)
async def get_model_catalog(request: Request) -> ModelCatalogResponse:
    """List provider-native chat models and generation defaults."""
    catalog: ModelCatalog = request.app.state.model_catalog
    snapshot = await catalog.available_models()
    return ModelCatalogResponse(
        provider=catalog.provider_name,
        default_model=catalog.default_model,
        models=[ModelOptionResponse(id=model, label=model) for model in snapshot.models],
        temperature=TemperatureOptionsResponse(
            min=0,
            max=2,
            step=0.1,
            default=catalog.default_temperature,
        ),
    )


# --- Definition CRUD -------------------------------------------------------------


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: CreateAgentRequest, request: Request, current_user: CurrentUser
) -> AgentResponse:
    """Create an agent definition owned by the authenticated user."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    try:
        definition = await definitions.create(owner_id=current_user.id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _agent_response(definition)


@router.get("", response_model=list[AgentResponse])
async def list_agents(request: Request, current_user: CurrentUser) -> list[AgentResponse]:
    """List agent definitions owned by the authenticated user."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    return [_agent_response(definition) for definition in await definitions.list(current_user.id)]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, request: Request, current_user: CurrentUser) -> AgentResponse:
    """Get one agent definition owned by the authenticated user."""
    definition = await _owned_definition(request, current_user.id, agent_id)
    return _agent_response(definition)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    payload: UpdateAgentRequest,
    request: Request,
    current_user: CurrentUser,
) -> AgentResponse:
    """Update an owned definition and advance its configuration version."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    try:
        definition = await definitions.update(
            current_user.id, agent_id, **payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return _agent_response(definition)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, request: Request, current_user: CurrentUser) -> None:
    """Delete an agent definition belonging to the authenticated user."""
    definitions: AgentDefinitionService = request.app.state.agent_definition_service
    if not await definitions.delete(current_user.id, agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")


# --- Persisted sessions ---------------------------------------------------------


@router.get(
    "/{agent_id}/sessions",
    response_model=list[SessionResponse],
    response_model_exclude_defaults=True,
)
async def list_agent_sessions(
    agent_id: str, request: Request, current_user: CurrentUser
) -> list[SessionResponse]:
    """List retained sessions for one owned agent, newest first."""
    await _owned_definition(request, current_user.id, agent_id)
    scoped_prefix = _scoped_session_id(current_user.id, agent_id, "")
    memory: Memory = request.app.state.session_memory
    checkpoints = await memory.list_checkpoints(scoped_prefix)
    return [
        _session_response(checkpoint, scoped_prefix)
        for checkpoint in checkpoints
        if checkpoint.session_id.startswith(scoped_prefix)
    ]


@router.get(
    "/{agent_id}/sessions/{session_id:path}",
    response_model=SessionResponse,
    response_model_exclude_defaults=True,
)
async def get_agent_session(
    agent_id: str,
    session_id: str,
    request: Request,
    current_user: CurrentUser,
) -> SessionResponse:
    """Fetch one retained session history for an owned agent."""
    await _owned_definition(request, current_user.id, agent_id)
    scoped_prefix = _scoped_session_id(current_user.id, agent_id, "")
    scoped_id = f"{scoped_prefix}{session_id}"
    memory: Memory = request.app.state.session_memory
    checkpoint = await memory.get_checkpoint(scoped_id)
    if checkpoint is None or checkpoint.session_id != scoped_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return _session_response(checkpoint, scoped_prefix)


@router.delete(
    "/{agent_id}/sessions/{session_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_agent_session(
    agent_id: str,
    session_id: str,
    request: Request,
    current_user: CurrentUser,
) -> None:
    """Delete one durable session belonging to an authenticated user's agent."""
    await _owned_definition(request, current_user.id, agent_id)
    scoped_id = _scoped_session_id(current_user.id, agent_id, session_id)
    memory: Memory = request.app.state.session_memory
    if not await memory.delete_checkpoint(scoped_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")


# --- Document ingestion (documents_router, not nested under /agents) --------------
# Documents belong to the authenticated user, not to one agent - see the module docstring.


@documents_router.get("", response_model=list[DocumentResponse])
async def list_owner_documents(
    request: Request, current_user: CurrentUser
) -> list[DocumentResponse]:
    """List successfully indexed sources for the authenticated user."""
    document_library: DocumentLibrary = request.app.state.rag_service
    documents = await document_library.list_documents({"owner_id": current_user.id})
    responses = [_source_response(document, current_user.id) for document in documents]
    return [response for response in responses if response is not None]


@documents_router.post("/text", response_model=IngestDocumentResponse)
async def ingest_owner_document(
    payload: IngestDocumentRequest, request: Request, current_user: CurrentUser
) -> IngestDocumentResponse:
    """Index a text document into the authenticated user's library."""
    return await _ingest(
        request.app.state.rag_service,
        text=payload.text,
        source_id=payload.source_id,
        owner_id=current_user.id,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )


@documents_router.post("/file", response_model=IngestDocumentResponse)
async def ingest_owner_file(
    request: Request,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    source_id: Annotated[str | None, Form()] = None,
) -> IngestDocumentResponse:
    """Extract and index a TXT, PDF, or DOCX file into the owner's document library."""
    filename, text = await _extract_uploaded_text(file)
    return await _ingest(
        request.app.state.rag_service,
        text=text,
        source_id=source_id or filename,
        owner_id=current_user.id,
    )


@documents_router.delete("/{source_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_owner_document(
    source_id: str, request: Request, current_user: CurrentUser
) -> None:
    """Delete one exact source document belonging to the authenticated user."""
    document_library: DocumentLibrary = request.app.state.rag_service
    deleted = await document_library.delete_document(
        {
            "owner_id": current_user.id,
            "source_id": f"{current_user.id}:{source_id}",
        }
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")


# --- Chat --------------------------------------------------------------------------


@router.post("/{agent_id}/chat/stream")
async def stream_with_agent(
    agent_id: str,
    payload: ChatRequest,
    request: Request,
    current_user: CurrentUser,
) -> StreamingResponse:
    """Stream a response from the caller's configured agent runtime.

    ``payload.files``, if any, are extracted and folded into this turn's
    answer only (see ``AgentService.run_stream``'s ``attachments``) - not
    persisted. For documents that should be searchable in future turns,
    use the ingestion routes above instead.
    """
    definition = await _owned_definition(request, current_user.id, agent_id)
    attachments = await _extract_attachments(payload.files)
    factory: AgentRuntimeFactory = request.app.state.agent_runtime_factory
    metadata, stream = await factory.get(definition).run_stream(
        session_id=_scoped_session_id(current_user.id, agent_id, payload.session_id),
        message=payload.message,
        tools=definition.allowed_tools,
        attachments=attachments,
    )
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
