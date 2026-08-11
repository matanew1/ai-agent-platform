"""Prompt templates used by the rag module."""

RERANK_PROMPT_TEMPLATE = """\
Query: {query}

Candidate passages:
{passages}

Rank the passages above by relevance to the query, most relevant first. \
Respond with ONLY a JSON array of passage numbers, e.g. [3, 1, 4, 2]. \
Include every passage number exactly once.
"""
