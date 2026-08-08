"""Private admin/test request and response models for RAG operations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.types import Chunk


class IngestDocumentRequest(BaseModel):
    """Document content to index through the private RAG API."""

    source_id: str
    text: str
    chunk_size: int = Field(default=500, gt=0)
    chunk_overlap: int = Field(default=50, ge=0)


class IngestDocumentResponse(BaseModel):
    """Result of private RAG document indexing."""

    source_id: str
    chunks_indexed: int


class SearchRequest(BaseModel):
    """Private semantic-search request."""

    query: str
    top_k: int = Field(default=5, gt=0)
    rerank: bool = True


class SearchResponse(BaseModel):
    """Private semantic-search result."""

    chunks: list[Chunk]
