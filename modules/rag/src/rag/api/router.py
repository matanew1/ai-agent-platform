"""HTTP endpoints for RAG document ingestion and semantic search."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from rag.api.schemas import (
    IngestDocumentRequest,
    IngestDocumentResponse,
    SearchRequest,
    SearchResponse,
)
from rag.service import RAGService
from shared.documents import extract_document_text

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/documents", response_model=IngestDocumentResponse)
async def ingest_document(
    payload: IngestDocumentRequest, request: Request
) -> IngestDocumentResponse:
    """Chunk and index a document for later semantic search."""
    rag_service: RAGService = request.app.state.rag_service
    chunks_indexed = await rag_service.ingest_document(
        text=payload.text,
        source_id=payload.source_id,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )
    return IngestDocumentResponse(source_id=payload.source_id, chunks_indexed=chunks_indexed)


@router.post("/documents/file", response_model=IngestDocumentResponse)
async def ingest_file(
    request: Request,
    file: Annotated[UploadFile, File()],
    source_id: Annotated[str | None, Form()] = None,
) -> IngestDocumentResponse:
    """Extract and index an uploaded TXT, PDF, or DOCX document."""
    filename = file.filename or "upload"
    try:
        text = await asyncio.to_thread(extract_document_text, filename, await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    rag_service: RAGService = request.app.state.rag_service
    source_id = source_id or filename
    chunks_indexed = await rag_service.ingest_document(text=text, source_id=source_id)
    return IngestDocumentResponse(source_id=source_id, chunks_indexed=chunks_indexed)


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, request: Request) -> SearchResponse:
    """Find indexed chunks relevant to a query."""
    rag_service: RAGService = request.app.state.rag_service
    chunks = await rag_service.search(query=payload.query, top_k=payload.top_k)
    return SearchResponse(chunks=chunks)
