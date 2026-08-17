"""Shared validation for a caller-supplied tools override against an agent.

Used by both ``chat.controller`` (an interactive turn's optional per-call
tool narrowing) and ``automation.controller`` (a schedule's own optional
tool narrowing) - both need the identical rule: a caller may narrow which
of an agent's already-authorized tools apply to one call/schedule, but
never widen beyond ``Agent.allowed_tools``, which stays the sole
authorization boundary (see ``.claude/rules/tool-conventions.md``).
"""

from __future__ import annotations

from shared.types import Agent


class ToolsNotAllowedError(ValueError):
    """Raised when a caller-supplied tools list isn't a subset of an agent's allowed_tools."""


def require_tools_subset(tools: list[str] | None, agent: Agent) -> None:
    """Raise unless every entry in ``tools`` is one of ``agent.allowed_tools``.

    ``tools=None`` means "no override" and always passes - the caller gets
    the agent's full ``allowed_tools``, same as today. An agent with an
    *empty* ``allowed_tools`` is itself unrestricted (see
    ``agent.controller``/``AgentConfigPanel``'s "empty list means allow
    all" convention), so there's no fixed universe to check a narrower
    selection against - any ``tools`` value is trivially a subset of
    "everything" and passes too.
    """
    if tools is None or not agent.allowed_tools:
        return
    unknown = sorted(set(tools) - set(agent.allowed_tools))
    if unknown:
        raise ToolsNotAllowedError(f"Tools not allowed for this agent: {unknown}")


__all__ = ["ToolsNotAllowedError", "require_tools_subset"]
