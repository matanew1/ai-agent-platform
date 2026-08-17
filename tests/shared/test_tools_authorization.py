"""Unit coverage for the shared agent-tool-authorization helper."""

from __future__ import annotations

import pytest

from shared.tools import ToolsNotAllowedError, require_tools_subset
from shared.types import Agent


def _agent(allowed_tools: list[str]) -> Agent:
    return Agent(
        id="agent-1",
        owner_id="owner-1",
        name="Test agent",
        system_prompt="Go.",
        allowed_tools=allowed_tools,
    )


def test_none_is_always_allowed() -> None:
    require_tools_subset(None, _agent(["fetch"]))  # no exception


def test_a_subset_of_the_agents_tools_is_allowed() -> None:
    require_tools_subset(["fetch"], _agent(["fetch", "extract_pdf"]))  # no exception


def test_a_tool_outside_the_agents_allowlist_is_rejected() -> None:
    with pytest.raises(ToolsNotAllowedError, match="shell_exec"):
        require_tools_subset(["fetch", "shell_exec"], _agent(["fetch"]))


def test_an_agent_with_no_allowlist_is_unrestricted() -> None:
    # Matches graph.graph._execute_tools's `if state.allowed_tools:` -
    # an empty list is falsy there, so it never filters, i.e. an agent with
    # allowed_tools=[] already has access to every registered tool. A
    # schedule/chat tools override for such an agent has no fixed universe
    # to be a subset of, so anything is valid.
    require_tools_subset(["anything_at_all"], _agent([]))  # no exception
