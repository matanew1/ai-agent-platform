"""Unit tests for rag.service.RAGService.

Uses a fake satisfying `rag.internal.ports.VectorStore` - no real Qdrant involved.
See `.claude/rules/testing.md`.
"""

from __future__ import annotations

from rag.service import RAGService

from shared.text import chunk_text
from shared.types import Chunk


class FakeVectorStore:
    """Fake satisfying rag.internal.ports.VectorStore."""

    def __init__(self) -> None:
        self.embedding: list[float] | None = None
        self.top_k: int | None = None
        self.chunks: list[Chunk] = []
        self.embeddings: list[list[float]] = []
        self.vector_size: int | None = None

    async def search(self, embedding: list[float], top_k: int = 5) -> list[Chunk]:
        self.embedding = embedding
        self.top_k = top_k
        return [Chunk(id="1", text="context", score=0.9)]

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self.chunks = chunks
        self.embeddings = embeddings

    async def ensure_collection(self, vector_size: int) -> None:
        self.vector_size = vector_size


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


def _make_rag_service() -> tuple[RAGService, FakeVectorStore]:
    vector_store = FakeVectorStore()
    return RAGService(vector_store=vector_store, embedder=FakeEmbedder()), vector_store


async def test_search_embeds_the_query_and_searches_the_vector_store() -> None:
    rag_service, vector_store = _make_rag_service()

    chunks = await rag_service.search("what is the deployment process?", top_k=3)

    assert [chunk.text for chunk in chunks] == ["context"]
    assert vector_store.embedding == [31.0, 1.0]
    assert vector_store.top_k == 3


async def test_ingest_document_chunks_embeds_and_indexes_text() -> None:
    rag_service, vector_store = _make_rag_service()

    indexed = await rag_service.ingest_document(
        text="abcdefgh", source_id="document-1", chunk_size=5, chunk_overlap=2
    )

    assert indexed == 2
    assert [chunk.text for chunk in vector_store.chunks] == ["abcde", "defgh"]
    assert vector_store.embeddings == [[5.0, 1.0], [5.0, 1.0]]
    assert vector_store.vector_size == 2


def test_chunk_text_keeps_headings_and_sentences_together() -> None:
    chunks = chunk_text(
        "# Deploy\n\nBuild the image. Run the migration.\n\n# Rollback\n\nRestore the backup.",
        chunk_size=35,
        chunk_overlap=10,
    )

    assert any(chunk.startswith("# Deploy\nBuild the image.") for chunk in chunks)
    assert any("Run the migration." in chunk for chunk in chunks)
    assert any(chunk.startswith("# Rollback\nRestore the backup.") for chunk in chunks)
