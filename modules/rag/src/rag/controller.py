"""HTTP routes for the authenticated user's shared document library.

Documents are deliberately not nested under ``/agents/{agent_id}`` - they
belong to the authenticated user, not to one agent, and every agent that
user owns shares the same pool (see ``graph.graph.OwnerScopedRetriever``).
Mounted from ``app/main.py``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from authentication.controller import current_user
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from rag.schemas import DocumentResponse, IngestDocumentRequest, IngestDocumentResponse
from rag.service import RAGService

from shared.auth import AuthenticatedUser
from shared.documents import extract_document_text
from shared.limits import DEFAULT_PAGE_LIMIT, MAX_DOCUMENT_BYTES, MAX_PAGE_LIMIT
from shared.types import Page

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=Page[DocumentResponse])
@current_user
async def list_owner_documents(
    request: Request,
    current_user: AuthenticatedUser,
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
) -> Page[DocumentResponse]:
    """List successfully indexed sources for the authenticated user, one page at a time.

    ``RAGService.list_documents`` aggregates chunk counts per source from every
    matching vector, so the full per-owner list is already computed before this
    slices it into a page - pagination here bounds the response payload and the
    web client's render cost, not the underlying vector-store query.
    """
    document_library: RAGService = request.app.state.rag_service
    documents = await document_library.list_documents({"owner_id": current_user.id})
    prefix = f"{current_user.id}:"
    owned = [document for document in documents if document.source_id.startswith(prefix)]
    page = owned[offset : offset + limit]
    return Page(
        items=[
            DocumentResponse(
                source_id=document.source_id.removeprefix(prefix),
                chunks_indexed=document.chunks_indexed,
            )
            for document in page
        ],
        total=len(owned),
        limit=limit,
        offset=offset,
    )


@router.post("/text", response_model=IngestDocumentResponse)
@current_user
async def ingest_owner_document(
    payload: IngestDocumentRequest, request: Request, current_user: AuthenticatedUser
) -> IngestDocumentResponse:
    """Index a text document into the authenticated user's library."""
    document_library: RAGService = request.app.state.rag_service
    chunks_indexed = await document_library.ingest_document(
        text=payload.text,
        source_id=f"{current_user.id}:{payload.source_id}",
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        metadata={"owner_id": current_user.id},
    )
    return IngestDocumentResponse(source_id=payload.source_id, chunks_indexed=chunks_indexed)


@router.post("/file", response_model=IngestDocumentResponse)
@current_user
async def ingest_owner_file(
    request: Request,
    current_user: AuthenticatedUser,
    file: Annotated[UploadFile, File()],
    source_id: Annotated[str | None, Form()] = None,
) -> IngestDocumentResponse:
    """Extract and index a TXT, PDF, or DOCX file into the owner's document library."""
    filename = file.filename or "upload"
    content = await file.read()
    if len(content) > MAX_DOCUMENT_BYTES:
        # Field(max_length=...) on IngestDocumentRequest.text covers
        # POST /documents/text; an UploadFile is read (and only then
        # sized) here instead, so this route needs its own check.
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB upload limit.",
        )
    try:
        text = await asyncio.to_thread(extract_document_text, filename, content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    resolved_source_id = source_id or filename
    document_library: RAGService = request.app.state.rag_service
    chunks_indexed = await document_library.ingest_document(
        text=text,
        source_id=f"{current_user.id}:{resolved_source_id}",
        metadata={"owner_id": current_user.id},
    )
    return IngestDocumentResponse(source_id=resolved_source_id, chunks_indexed=chunks_indexed)


@router.delete("/{source_id:path}", status_code=status.HTTP_204_NO_CONTENT)
@current_user
async def delete_owner_document(
    source_id: str, request: Request, current_user: AuthenticatedUser
) -> None:
    """Delete one exact source document belonging to the authenticated user."""
    document_library: RAGService = request.app.state.rag_service
    deleted = await document_library.delete_document(
        {
            "owner_id": current_user.id,
            "source_id": f"{current_user.id}:{source_id}",
        }
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
