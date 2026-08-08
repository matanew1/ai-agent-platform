"""LLM-based reranking of vector-search candidates.

Vector similarity (cosine distance between two embeddings) is a coarse
signal - it never sees the query and the passage together, only their
independently-computed vectors. An LLM reading both at once gives a more
precise relevance judgment at the cost of a real generation call, so this
is applied as a second pass over a wider candidate set from
``VectorStore.search``, not a replacement for it - see
``rag.service.RAGService.search``.
"""

from __future__ import annotations

import json
import logging

from rag.internal.ports import LLMProvider
from rag.internal.prompts import RERANK_PROMPT_TEMPLATE
from shared.types import Chunk

logger = logging.getLogger(__name__)

# A ranking response is a JSON array of every candidate index - it has to
# scale with candidate count, not be a flat cap: top_k has no enforced
# upper bound (RAGService.search's caller controls it), and candidate_k
# grows with it (top_k * 4), so a wide-enough search can produce a ranking
# array a flat 100-token cap would truncate before the closing bracket -
# see _parse_ranking's bracket check, and the regression test for exactly
# this. Kept as tight as the candidate count allows for the same reason
# agent.internal.graph._TOOL_CALL_MAX_TOKENS is: a decision-only call
# doesn't need room for prose, and a smaller cap means a faster response.
_RERANK_BASE_TOKENS = 20
_RERANK_TOKENS_PER_CANDIDATE = 6


async def rerank_chunks(
    llm: LLMProvider, query: str, chunks: list[Chunk], top_k: int
) -> list[Chunk]:
    """Reorder ``chunks`` by LLM-judged relevance to ``query``, keeping the best ``top_k``.

    Never raises: a failed LLM call or an unparseable response falls back
    to the vector-search order the chunks already arrived in, sliced to
    ``top_k`` - reranking is a quality enhancement, not something a search
    should fail over, the same contract
    ``tool.registry.ToolRegistry.call_tool`` holds for tool execution (see
    ``.claude/rules/tool-conventions.md``).

    Args:
        llm: Used to judge relevance - never raises, see above.
        query: The user's natural-language query.
        chunks: Candidates to rerank, in their original (vector-search)
            order. Should be a wider set than ``top_k`` for reranking to
            have anything to select from - see ``RAGService.search``.
        top_k: Maximum number of chunks to return.

    Returns:
        Up to ``top_k`` chunks, most relevant first per the LLM's
        judgment. Note this may no longer be in descending ``.score``
        order - ``.score`` still reflects vector similarity, not the
        rerank outcome, since the LLM produces an order, not a new score
        per chunk.
    """
    if not chunks:
        return chunks
    passages = "\n".join(f"{index + 1}. {chunk.text}" for index, chunk in enumerate(chunks))
    prompt = RERANK_PROMPT_TEMPLATE.format(query=query, passages=passages)
    max_tokens = _RERANK_BASE_TOKENS + len(chunks) * _RERANK_TOKENS_PER_CANDIDATE
    try:
        raw = await llm.generate(prompt, max_tokens=max_tokens)
    except Exception as exc:
        logger.warning("Reranking failed, keeping vector-search order: %s", exc)
        return chunks[:top_k]

    order = _parse_ranking(raw, len(chunks))
    return [chunks[index] for index in order[:top_k]]


def _parse_ranking(raw: str, count: int) -> list[int]:
    """Parse a 0-based reordering of ``count`` candidate indices from ``raw``.

    Falls back to the natural (unreranked) order whenever ``raw`` can't be
    parsed as a JSON array, and appends any index the model didn't
    mention at the end, in original order - a partial or malformed
    ranking should make the result *worse-ordered*, never *shorter*.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()

    natural_order = list(range(count))
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        # No closing bracket most often means the response got cut off by
        # max_tokens before finishing the array (see _RERANK_BASE_TOKENS/
        # _RERANK_TOKENS_PER_CANDIDATE) - log it the same as a JSON parse
        # failure below, so a too-tight budget for a given candidate count
        # is observable instead of silently degrading to no reranking.
        logger.warning(
            "Reranking response had no complete JSON array (len=%d) - "
            "likely truncated by max_tokens",
            len(raw),
        )
        return natural_order

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Could not parse reranking response as JSON (len=%d)", len(raw))
        return natural_order
    if not isinstance(parsed, list):
        return natural_order

    seen: set[int] = set()
    order: list[int] = []
    for value in parsed:
        index = value - 1 if isinstance(value, int) else None
        if index is not None and 0 <= index < count and index not in seen:
            seen.add(index)
            order.append(index)
    order.extend(index for index in natural_order if index not in seen)
    return order
