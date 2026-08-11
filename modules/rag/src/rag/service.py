"""RAG service: the module's public entry point.

Used by ``graph.graph.OwnerScopedRetriever`` for retrieval and by this
module's own ``rag.controller``'s document routes for ingestion/listing/
deletion. No ``Retriever``/``DocumentLibrary`` port: this is ``rag``'s only
implementation, and agent depends on it the same direct way it depends on
``tool.service.ToolService`` - see ``.claude/rules/architecture.md``'s
"Avoiding over-engineering".
"""

from __future__ import annotations

import logging

from rag.repository import RagRepository

from infrastructure.llm.protocol import EmbeddingClient
from shared.text import chunk_text
from shared.types import Chunk, IndexedDocument

logger = logging.getLogger(__name__)


class RAGService:
    """Coordinates document retrieval and ingestion for the agent.

    Args:
        vector_store: Vector store adapter (``rag.repository.RagRepository``).
        embedder: Turns text into vectors for indexing and querying.
    """

    def __init__(
        self,
        vector_store: RagRepository,
        embedder: EmbeddingClient,
    ) -> None:
        self._vector_store = vector_store
        self._embedder = embedder

    async def ingest_document(
        self,
        text: str,
        source_id: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        metadata: dict[str, str] | None = None,
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
                metadata={"source_id": source_id, **(metadata or {})},
            )
            for index, chunk in enumerate(texts)
        ]
        embeddings = [await self._embedder.embed(chunk.text) for chunk in chunks]
        await self._vector_store.ensure_collection(len(embeddings[0]))
        await self._vector_store.upsert(chunks, embeddings)
        return len(chunks)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[Chunk]:
        """Search for chunks relevant to a query.

        Args:
            query: Natural-language query.
            top_k: Maximum number of chunks to return.

        Returns:
            Relevant chunks, most relevant first by vector similarity.
        """
        # Length, not content - a query can carry sensitive user data (see
        # infrastructure.llm.ollama's generate() for the same policy).
        logger.debug("RAGService.search query_len=%d top_k=%d", len(query), top_k)
        embedding = await self._embedder.embed(query)
        return await self._search_vectors(embedding, top_k, metadata_filter)

    async def list_documents(self, metadata_filter: dict[str, str]) -> list[IndexedDocument]:
        """Aggregate stored chunks into one record per source document."""
        chunks = await self._vector_store.list_chunks(metadata_filter)
        counts: dict[str, int] = {}
        for chunk in chunks:
            source_id = chunk.metadata.get("source_id")
            if source_id:
                counts[source_id] = counts.get(source_id, 0) + 1
        return [
            IndexedDocument(source_id=source_id, chunks_indexed=count)
            for source_id, count in sorted(counts.items())
        ]

    async def delete_document(self, metadata_filter: dict[str, str]) -> bool:
        """Delete one exact document selection from the vector store."""
        return await self._vector_store.delete_chunks(metadata_filter) > 0

    async def _search_vectors(
        self, embedding: list[float], top_k: int, metadata_filter: dict[str, str] | None
    ) -> list[Chunk]:
        """Call the vector store with a metadata filter only when needed."""
        if metadata_filter is None:
            return await self._vector_store.search(embedding, top_k)
        return await self._vector_store.search(embedding, top_k, metadata_filter=metadata_filter)


__all__ = ["RAGService"]
