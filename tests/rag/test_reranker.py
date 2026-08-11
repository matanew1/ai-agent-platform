"""Unit tests for rag.reranker.rerank_chunks.

Fake satisfying rag.ports.LLMProvider - no real LLM involved.
See .claude/rules/testing.md.
"""

from __future__ import annotations

from rag.reranker import rerank_chunks

from shared.types import Chunk


class FakeLLMProvider:
    """Fake satisfying rag.ports.LLMProvider.

    Args:
        response: Text returned from every ``generate`` call. ``None``
            makes ``generate`` raise instead, to exercise the fallback.
    """

    def __init__(self, response: str | None = "[]") -> None:
        self._response = response
        self.prompts: list[str] = []
        self.max_tokens_requested: list[int | None] = []

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        self.prompts.append(prompt)
        self.max_tokens_requested.append(max_tokens)
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


async def test_max_tokens_scales_with_candidate_count() -> None:
    """Regression test: a flat max_tokens cap doesn't scale with the
    candidate set, and a wide enough search (top_k has no enforced upper
    bound) can produce a ranking array long enough to get truncated before
    the closing bracket - see _RERANK_BASE_TOKENS/_RERANK_TOKENS_PER_CANDIDATE.
    """
    llm = FakeLLMProvider(response="[]")

    await rerank_chunks(llm, "query", _chunks(*[f"doc{i}" for i in range(3)]), top_k=3)
    await rerank_chunks(llm, "query", _chunks(*[f"doc{i}" for i in range(40)]), top_k=3)

    small_request, large_request = llm.max_tokens_requested
    assert large_request > small_request


async def test_falls_back_and_logs_when_the_ranking_array_is_truncated() -> None:
    """The no-closing-bracket case (a response cut off mid-array by
    max_tokens) must fall back the same as an unparseable one - this is
    the failure mode _RERANK_BASE_TOKENS/_RERANK_TOKENS_PER_CANDIDATE
    exists to make rare, not something a caller should get an empty/wrong
    result from silently.
    """
    chunks = _chunks("apple", "banana", "cherry")
    llm = FakeLLMProvider(response="[3, 1, 2")  # never closes

    result = await rerank_chunks(llm, "query", chunks, top_k=3)

    assert [c.text for c in result] == ["apple", "banana", "cherry"]
