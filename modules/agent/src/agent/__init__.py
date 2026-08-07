"""Agent orchestration module.

Owns the LangGraph workflow, agent state, and prompts, and depends only on
the abstractions in ``agent.internal.ports`` - never on a concrete database, cache,
vector store, or LLM SDK directly. Concrete implementations are wired in at
the composition root (``app/lifespan.py``). See
``.claude/rules/architecture.md``.
"""

from agent.service import AgentService

__all__ = ["AgentService"]
