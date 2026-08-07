"""Pydantic models for RAG HTTP requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.types import Chunk


class IngestDocumentRequest(BaseModel):
    """Document content to add to the knowledge base."""

    source_id: str
    text: str
    chunk_size: int = Field(default=500, gt=0)
    chunk_overlap: int = Field(default=50, ge=0)


class IngestDocumentResponse(BaseModel):
    """Result of indexing a document."""

    source_id: str
    chunks_indexed: int


class SearchRequest(BaseModel):
    """Semantic search request."""

    query: str
    top_k: int = Field(default=5, gt=0)


class SearchResponse(BaseModel):
    """Semantic search results."""

    chunks: list[Chunk]
