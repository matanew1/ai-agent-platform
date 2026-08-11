"""Unit tests for Qdrant document-library operations."""

from __future__ import annotations

from types import SimpleNamespace

from infrastructure.qdrant import QdrantVectorStore


class _QdrantClient:
    def __init__(self) -> None:
        self.scroll_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.matching_count = 0

    async def collection_exists(self, collection_name: str) -> bool:
        return True

    async def scroll(self, **kwargs: object):
        self.scroll_calls.append(kwargs)
        if kwargs["offset"] is None:
            return (
                [
                    SimpleNamespace(
                        id="point-1",
                        payload={
                            "chunk_id": "source:0",
                            "text": "first",
                            "metadata": {"owner_id": "owner-1", "source_id": "owner-1:a"},
                        },
                    )
                ],
                "next-page",
            )
        return (
            [
                SimpleNamespace(
                    id="point-2",
                    payload={
                        "chunk_id": "source:1",
                        "text": "second",
                        "metadata": {"owner_id": "owner-1", "source_id": "owner-1:a"},
                    },
                )
            ],
            None,
        )

    async def count(self, **kwargs: object):
        return SimpleNamespace(count=self.matching_count)

    async def delete(self, **kwargs: object):
        self.delete_calls.append(kwargs)


def _store(client: _QdrantClient) -> QdrantVectorStore:
    """Build the adapter around a fake without opening a real Qdrant client."""
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store._collection_name = "documents"
    store._client = client
    return store


async def test_list_chunks_scrolls_all_pages_with_owner_filter() -> None:
    client = _QdrantClient()
    store = _store(client)

    chunks = await store.list_chunks({"owner_id": "owner-1"})

    assert [chunk.id for chunk in chunks] == ["source:0", "source:1"]
    assert [call["offset"] for call in client.scroll_calls] == [None, "next-page"]
    point_filter = client.scroll_calls[0]["scroll_filter"]
    assert point_filter.must[0].key == "metadata.owner_id"
    assert point_filter.must[0].match.value == "owner-1"


async def test_delete_chunks_counts_before_deleting_exact_selection() -> None:
    client = _QdrantClient()
    client.matching_count = 2
    store = _store(client)

    deleted = await store.delete_chunks({"owner_id": "owner-1", "source_id": "owner-1:report.pdf"})

    assert deleted == 2
    assert len(client.delete_calls) == 1
    point_filter = client.delete_calls[0]["points_selector"]
    assert [condition.key for condition in point_filter.must] == [
        "metadata.owner_id",
        "metadata.source_id",
    ]


async def test_delete_chunks_refuses_an_empty_filter() -> None:
    client = _QdrantClient()
    client.matching_count = 10
    store = _store(client)

    deleted = await store.delete_chunks({})

    assert deleted == 0
    assert client.delete_calls == []
