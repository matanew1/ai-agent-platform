"""Unit tests for agent.runtime.OwnerScopedRetriever."""

from __future__ import annotations

from agent.runtime import AgentRuntimeFactory, OwnerScopedRetriever

from shared.types import AgentDefinition, Chunk


class FakeRetriever:
    """Fake satisfying agent.ports.Retriever, recording the filter it was called with."""

    def __init__(self, chunks: list[Chunk] | None = None) -> None:
        self._chunks = chunks if chunks is not None else [Chunk(id="1", text="doc", score=0.9)]
        self.metadata_filters: list[dict[str, str] | None] = []

    async def search(
        self, query: str, top_k: int = 5, metadata_filter: dict[str, str] | None = None
    ) -> list[Chunk]:
        self.metadata_filters.append(metadata_filter)
        return self._chunks[:top_k]


class FakeConfigurableLLM:
    """Records the per-agent options requested by the runtime factory."""

    def __init__(self) -> None:
        self.options: list[tuple[str | None, float | None]] = []

    def with_options(
        self, *, model: str | None = None, temperature: float | None = None
    ) -> FakeConfigurableLLM:
        self.options.append((model, temperature))
        return self


async def test_search_scopes_by_owner_id_only() -> None:
    retriever = FakeRetriever()
    scoped = OwnerScopedRetriever(retriever, owner_id="owner-1")

    await scoped.search("query")

    assert retriever.metadata_filters == [{"owner_id": "owner-1"}]


async def test_search_returns_the_underlying_retrievers_results() -> None:
    chunks = [Chunk(id="1", text="a", score=0.9), Chunk(id="2", text="b", score=0.8)]
    retriever = FakeRetriever(chunks)
    scoped = OwnerScopedRetriever(retriever, owner_id="owner-1")

    results = await scoped.search("query", top_k=2)

    assert results == chunks


def test_runtime_applies_generation_options_once_per_definition_version() -> None:
    llm = FakeConfigurableLLM()
    factory = AgentRuntimeFactory(
        llm=llm,
        retriever=FakeRetriever(),
        memory=object(),
        tool_registry=object(),
    )
    definition = AgentDefinition(
        owner_id="owner-1",
        name="Researcher",
        system_prompt="Research carefully.",
        model="qwen3:14b",
        temperature=0.3,
    )

    first = factory.get(definition)
    second = factory.get(definition)

    assert first is second
    assert llm.options == [("qwen3:14b", 0.3)]
