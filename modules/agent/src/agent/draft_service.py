"""Rewrite a user's draft chat message using one agent's own configuration.

A single, stateless, non-streamed LLM call - no session, no history, no tool
execution. Kept out of ``AgentService`` on purpose: that class is
versioned-configuration CRUD (see its own docstring on why that's separate
from turn *execution*), and generating text is a third, distinct
responsibility that doesn't belong in either.
"""

from __future__ import annotations

from agent.prompt import REWRITE_DRAFT_PROMPT_TEMPLATE
from agent.service import AgentService
from tool.service import ToolService

from infrastructure.llm.protocol import LanguageModelClient
from shared.prompt_formatters import format_tools


class DraftService:
    """Turns a rough chat draft into a clearer instruction for one owned agent."""

    def __init__(
        self,
        agent_service: AgentService,
        tool_registry: ToolService,
        model_catalog: LanguageModelClient,
    ) -> None:
        self._agent_service = agent_service
        self._tool_registry = tool_registry
        self._model_catalog = model_catalog

    async def rewrite(self, owner_id: str, agent_id: str, draft: str) -> str | None:
        """Rewrite ``draft`` for the given agent, or ``None`` if it isn't owned by ``owner_id``.

        Args:
            owner_id: The authenticated caller - ownership is checked the same way
                every other agent-scoped operation does (``AgentService.get``).
            agent_id: The agent whose system prompt and allowed tools frame the rewrite.
            draft: The user's draft message, as typed so far.

        Returns:
            The rewritten message, or ``None`` if no agent with ``agent_id`` is owned
            by ``owner_id`` (the caller maps this to 404).

        Raises:
            PlatformError: The underlying LLM call failed - translated by the
                ``infrastructure.llm`` adapter before it reaches here.
        """
        agent = await self._agent_service.get(owner_id, agent_id)
        if agent is None:
            return None

        tools = self._tool_registry.get_tools()
        if agent.allowed_tools:
            allowed = set(agent.allowed_tools)
            tools = [tool for tool in tools if tool.name in allowed]

        prompt = REWRITE_DRAFT_PROMPT_TEMPLATE.format(
            system_prompt=agent.system_prompt,
            tools=format_tools(tools),
            draft=draft,
        )
        llm = self._model_catalog.with_options(model=agent.model, temperature=agent.temperature)
        rewritten = await llm.generate(prompt)
        return rewritten.strip()
