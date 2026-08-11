"""RAG service: the module's public entry point."""

from __future__ import annotations

import logging

from rag.ports import Embedder, LLMProvider, VectorStore
from rag.reranker import rerank_chunks
from shared.text import chunk_text
from shared.types import Chunk, IndexedDocument

logger = logging.getLogger(__name__)

# How much wider a candidate set to pull from the vector store before
# reranking cuts it down to top_k - reranking can only reorder what it's
# given, so it needs room to promote a result vector search ranked lower.
# max() with a floor keeps a small top_k (e.g. 1) from starving the
# reranker of anything to actually choose between.
_RERANK_CANDIDATE_MULTIPLIER = 4
_MIN_RERANK_CANDIDATES = 10


class RAGService:
    """Coordinates document retrieval for the agent.

    Args:
        vector_store: Vector store implementation (see
            ``rag.ports.VectorStore``).
        embedder: Turns text into vectors for indexing and querying.
        llm: Optional - when set, ``search`` reranks a wider vector-search
            candidate set with it before returning ``top_k`` (see
            ``rag.reranker.rerank_chunks``). ``None`` (the
            default) skips reranking entirely: ``search`` costs exactly
            one embedding call, same as before this existed.
    """

    def __init__(
        self, vector_store: VectorStore, embedder: Embedder, llm: LLMProvider | None = None
    ) -> None:
        self._vector_store = vector_store
        self._embedder = embedder
        self._llm = llm

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
        rerank: bool = True,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[Chunk]:
        """Search for chunks relevant to a query.

        Args:
            query: Natural-language query.
            top_k: Maximum number of chunks to return.
            rerank: Whether to rerank the vector-search candidates with the
                configured ``llm`` before returning ``top_k`` of them - a
                per-call opt-out for when plain vector-search speed matters
                more than the accuracy reranking adds (see
                ``rag.reranker`` for the measured trade-off).
                Ignored (no-ops to plain vector search) when no ``llm`` was
                configured in the first place - this never raises just
                because reranking isn't available to turn on.

        Returns:
            Relevant chunks, most relevant first - by vector similarity if
            reranking is off or unavailable, by reranked LLM judgment
            otherwise.
        """
        # Length, not content - a query can carry sensitive user data (see
        # infrastructure/llm.py's generate() for the same policy).
        logger.debug("RAGService.search query_len=%d top_k=%d rerank=%s", len(query), top_k, rerank)
        embedding = await self._embedder.embed(query)
        if self._llm is None or not rerank:
            return await self._search_vectors(embedding, top_k, metadata_filter)

        candidate_k = max(top_k * _RERANK_CANDIDATE_MULTIPLIER, _MIN_RERANK_CANDIDATES)
        candidates = await self._search_vectors(embedding, candidate_k, metadata_filter)
        return await rerank_chunks(self._llm, query, candidates, top_k)

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
