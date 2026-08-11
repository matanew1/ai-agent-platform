"""Pydantic request and response models for the user-scoped document library."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IngestDocumentRequest(BaseModel):
    """Text document content to add to one owner's shared knowledge base."""

    source_id: str
    text: str
    chunk_size: int = Field(default=500, gt=0)
    chunk_overlap: int = Field(default=50, ge=0)


class IngestDocumentResponse(BaseModel):
    """Result of indexing one owner-scoped document."""

    source_id: str
    chunks_indexed: int


class DocumentResponse(BaseModel):
    """One source currently available in an owner's document index."""

    source_id: str
    chunks_indexed: int
    status: Literal["indexed"] = "indexed"
