"""Prompt template(s) for agent-configuration-level LLM calls.

Distinct from ``graph.prompt`` on purpose: those templates drive turn
*execution* (tool routing, answer generation) inside a running chat turn.
This one is a single, stateless, non-streamed call keyed only off an
agent's *definition* (system prompt, allowed tools) - see
``agent.draft_service.DraftService``.
"""

from __future__ import annotations

REWRITE_DRAFT_PROMPT_TEMPLATE = """\
An agent is configured like this:

{system_prompt}

It has access to these tools:
{tools}

A user is about to send this agent the following draft message:
{draft}

Rewrite the draft into a clearer, more complete instruction for this specific agent - \
resolve vague requests into something the agent can act on directly, and mention a \
relevant tool by name only if the draft's intent clearly needs it. Preserve the \
user's original meaning and language; do not invent details the draft didn't imply. \
Return ONLY the rewritten message: no preamble, no quotes, no explanation.
"""
