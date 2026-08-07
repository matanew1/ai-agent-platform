"""RAG service: the module's public entry point."""

from __future__ import annotations

import logging

from rag.internal.ports import Embedder, VectorStore
from shared.text import chunk_text
from shared.types import Chunk

logger = logging.getLogger(__name__)


class RAGService:
    """Coordinates document retrieval for the agent.

    Args:
        vector_store: Vector store implementation (see
            ``rag.internal.ports.VectorStore``).
    """

    def __init__(self, vector_store: VectorStore, embedder: Embedder) -> None:
        self._vector_store = vector_store
        self._embedder = embedder

    async def ingest_document(
        self,
        text: str,
        source_id: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> int:
        """Chunk, embed, and index a document."""
        logger.debug(
            "RAGService.ingest_document source_id=%r text_len=%d chunk_size=%d chunk_overlap=%d",
            source_id,
            len(text),
            chunk_size,
            chunk_overlap,
        )
        texts = chunk_text(text, chunk_size, chunk_overlap)
        if not texts:
            return 0

        chunks = [
            Chunk(
                id=f"{source_id}:{index}",
                text=chunk,
                score=0.0,
                metadata={"source_id": source_id},
            )
            for index, chunk in enumerate(texts)
        ]
        embeddings = [await self._embedder.embed(chunk.text) for chunk in chunks]
        await self._vector_store.ensure_collection(len(embeddings[0]))
        await self._vector_store.upsert(chunks, embeddings)
        return len(chunks)

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Search for chunks relevant to a query.

        Args:
            query: Natural-language query.
            top_k: Maximum number of chunks to return.

        Returns:
            Relevant chunks, most relevant first.
        """
        # Length, not content - a query can carry sensitive user data (see
        # infrastructure/llm.py's generate() for the same policy).
        logger.debug("RAGService.search query_len=%d top_k=%d", len(query), top_k)
        embedding = await self._embedder.embed(query)
        return await self._vector_store.search(embedding, top_k)
