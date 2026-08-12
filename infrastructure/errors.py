"""Provider-neutral errors raised by external capability implementations."""

from __future__ import annotations

from shared.types import PlatformError


class DatabaseError(PlatformError):
    """Raised when a document-store operation fails."""


class CacheError(PlatformError):
    """Raised when a cache-store operation fails."""


class VectorDatabaseError(PlatformError):
    """Raised when a vector-record-store operation fails."""


class LLMError(PlatformError):
    """Raised when an LLM call fails."""


class EmbeddingError(PlatformError):
    """Raised when an embedding request fails."""


class RagError(PlatformError):
    """Base exception raised by the RAG module."""


__all__ = [
    "RagError",
    "CacheError",
    "DatabaseError",
    "VectorDatabaseError",
    "LLMError",
    "EmbeddingError",
]
