"""Unit tests for rag.internal.reranker.rerank_chunks.

Fake satisfying rag.internal.ports.LLMProvider - no real LLM involved.
See .claude/rules/testing.md.
"""

from __future__ import annotations

from rag.internal.reranker import rerank_chunks

from shared.types import Chunk


class FakeLLMProvider:
    """Fake satisfying rag.internal.ports.LLMProvider.

    Args:
        response: Text returned from every ``generate`` call. ``None``
            makes ``generate`` raise instead, to exercise the fallback.
    """

    def __init__(self, response: str | None = "[]") -> None:
        self._response = response
        self.prompts: list[str] = []

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        self.prompts.append(prompt)
        if self._response is None:
            raise RuntimeError("simulated LLM failure")
        return self._response


def _chunks(*texts: str) -> list[Chunk]:
    return [Chunk(id=str(i), text=text, score=1.0 - i * 0.1) for i, text in enumerate(texts)]


async def test_reorders_chunks_per_the_llm_ranking() -> None:
    chunks = _chunks("apple", "banana", "cherry")
    llm = FakeLLMProvider(response="[3, 1, 2]")

    result = await rerank_chunks(llm, "query", chunks, top_k=3)

    assert [c.text for c in result] == ["cherry", "apple", "banana"]


async def test_slices_to_top_k_after_reranking() -> None:
    chunks = _chunks("apple", "banana", "cherry")
    llm = FakeLLMProvider(response="[3, 1, 2]")

    result = await rerank_chunks(llm, "query", chunks, top_k=2)

    assert [c.text for c in result] == ["cherry", "apple"]


async def test_the_prompt_lists_every_candidate_and_the_query() -> None:
    chunks = _chunks("apple", "banana")
    llm = FakeLLMProvider(response="[]")

    await rerank_chunks(llm, "which fruit?", chunks, top_k=2)

    (prompt,) = llm.prompts
    assert "which fruit?" in prompt
    assert "1. apple" in prompt
    assert "2. banana" in prompt


async def test_falls_back_to_vector_search_order_when_the_llm_raises() -> None:
    chunks = _chunks("apple", "banana", "cherry")
    llm = FakeLLMProvider(response=None)

    result = await rerank_chunks(llm, "query", chunks, top_k=2)

    assert [c.text for c in result] == ["apple", "banana"]


async def test_falls_back_to_vector_search_order_on_unparseable_response() -> None:
    chunks = _chunks("apple", "banana")
    llm = FakeLLMProvider(response="I think apple is more relevant.")

    result = await rerank_chunks(llm, "query", chunks, top_k=2)

    assert [c.text for c in result] == ["apple", "banana"]


async def test_a_partial_ranking_appends_unmentioned_chunks_instead_of_dropping_them() -> None:
    chunks = _chunks("apple", "banana", "cherry")
    llm = FakeLLMProvider(response="[2]")  # only mentions "banana"

    result = await rerank_chunks(llm, "query", chunks, top_k=3)

    assert [c.text for c in result] == ["banana", "apple", "cherry"]


async def test_out_of_range_and_duplicate_indices_are_ignored() -> None:
    chunks = _chunks("apple", "banana")
    llm = FakeLLMProvider(response="[9, 2, 2, 0]")

    result = await rerank_chunks(llm, "query", chunks, top_k=2)

    assert [c.text for c in result] == ["banana", "apple"]


async def test_no_candidates_returns_empty_without_calling_the_llm() -> None:
    llm = FakeLLMProvider(response="[]")

    result = await rerank_chunks(llm, "query", [], top_k=5)

    assert result == []
    assert llm.prompts == []


async def test_a_code_fenced_response_is_still_parsed() -> None:
    chunks = _chunks("apple", "banana")
    llm = FakeLLMProvider(response="```json\n[2, 1]\n```")

    result = await rerank_chunks(llm, "query", chunks, top_k=2)

    assert [c.text for c in result] == ["banana", "apple"]
