"""Private admin/test routes for raw RAG operations."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from rag.api.schemas import (
    IngestDocumentRequest,
    IngestDocumentResponse,
    SearchRequest,
    SearchResponse,
)
from rag.service import RAGService
from shared.documents import extract_document_text

router = APIRouter(prefix="/admin/rag", tags=["[ADMIN ONLY] RAG"])


@router.post(
    "/documents",
    response_model=IngestDocumentResponse,
    summary="[ADMIN ONLY] Index RAG text",
)
async def ingest_document(
    payload: IngestDocumentRequest, request: Request
) -> IngestDocumentResponse:
    """Index a document directly for private retrieval testing."""
    rag_service: RAGService = request.app.state.rag_service
    chunks_indexed = await rag_service.ingest_document(
        text=payload.text,
        source_id=payload.source_id,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )
    return IngestDocumentResponse(source_id=payload.source_id, chunks_indexed=chunks_indexed)


@router.post(
    "/documents/file",
    response_model=IngestDocumentResponse,
    summary="[ADMIN ONLY] Index RAG file",
)
async def ingest_file(
    request: Request,
    file: Annotated[UploadFile, File()],
    source_id: Annotated[str | None, Form()] = None,
) -> IngestDocumentResponse:
    """Extract and index a file directly for private retrieval testing."""
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
    chunks_indexed = await rag_service.ingest_document(text=text, source_id=document_source_id)
    return IngestDocumentResponse(source_id=document_source_id, chunks_indexed=chunks_indexed)


@router.post("/search", response_model=SearchResponse, summary="[ADMIN ONLY] Search raw RAG")
async def search(payload: SearchRequest, request: Request) -> SearchResponse:
    """Search raw RAG data directly for private diagnostics."""
    rag_service: RAGService = request.app.state.rag_service
    chunks = await rag_service.search(
        query=payload.query,
        top_k=payload.top_k,
        rerank=payload.rerank,
    )
    return SearchResponse(chunks=chunks)
