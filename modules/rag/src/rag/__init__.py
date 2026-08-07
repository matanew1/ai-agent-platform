"""Retrieval-augmented generation module.

Owns chunking, ingestion, and retrieval. Depends only on the
``VectorStore`` port in ``rag.internal.ports`` - never on Qdrant directly. See
``.claude/rules/architecture.md``.
"""

from rag.service import RAGService

__all__ = ["RAGService"]
