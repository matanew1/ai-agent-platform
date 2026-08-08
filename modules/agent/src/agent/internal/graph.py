"""Everything the agent's LangGraph workflow needs: state, error type,
and the graph itself.

    START -> retrieve_context ---\\
          -> execute_tools    ---+--> generate_answer -> END

``retrieve_context`` and ``execute_tools`` only depend on the user's raw
input, not on each other, so they run as parallel branches - LangGraph
runs both in the same step and waits for both before ``generate_answer``.
A prior version routed through a per-step ``supervisor`` LLM call before
every node; it was removed because the routing was always deterministic
(there's no branching logic that actually skips a step yet) and it more
than doubled the number of sequential LLM round-trips per turn for no
behavioral benefit - see ``.claude/rules/architecture.md``. A ``planner``
node sat before both branches after that, producing a one-sentence "plan"
- it was removed too, once it turned out to have exactly one consumer
(``execute_tools``'s tool-call prompt below) that already skips itself via
``_mentions_a_tool`` on most turns, so the planner's own LLM call ran and
was silently discarded far more often than it was used. Both
``retrieve_context`` and ``execute_tools`` now have their own cheap local
heuristic (``_is_smalltalk``, ``_mentions_a_tool``) to skip their LLM/
retrieval work outright when it's clearly not needed, instead of a
dedicated planning step deciding that for them.

Prompt templates live in ``agent.internal.prompts``. `agent.internal.ports`
stays separate as the module's dependency contract.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from agent.internal.ports import LLMProvider, Retriever, ToolRegistry
from agent.internal.prompts import (
    GENERATE_ANSWER_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
    TOOL_CALL_PROMPT_TEMPLATE,
)
from shared.prompt_formatters import (
    format_context,
    format_history,
    format_tool_results,
    format_tools,
)
from shared.tool_calls import parse_tool_calls
from shared.types import ChatMessage, Chunk, PlatformError, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

# Decision-only calls (a JSON tool-call array) never need more than a few
# dozen tokens - capping them cuts generation time without touching answer
# quality. generate_answer is deliberately left uncapped (None): it
# produces the actual user-facing reply.
#
# The cap covers *generated* tokens, which on a reasoning-capable model
# (qwen3, gpt-oss, deepseek-r1) includes the thinking tokens emitted before
# any visible output - so "a few dozen tokens of JSON" can still blow a
# 200-token budget and come back empty. Run those models with reasoning off
# (OLLAMA_REASONING=false) for this to hold. It's no longer a silent
# failure either way: infrastructure/llm.py's _require_content raises
# instead of returning the empty string that used to parse into zero tool
# calls.
_TOOL_CALL_MAX_TOKENS = 200

# Smalltalk/acknowledgement messages with no informational content - see
# _is_smalltalk below. Kept as an exact-match set (not substring/prefix
# matching): a prefix match on "hi" would also match "hi, what's the
# mongodb timeout?", which very much needs retrieval.
_SMALLTALK_MESSAGES = {
    "hi",
    "hello",
    "hey",
    "yo",
    "thanks",
    "thank you",
    "thx",
    "ty",
    "bye",
    "goodbye",
    "see you",
    "ok",
    "okay",
    "cool",
    "nice",
    "great",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "what's up",
    "whats up",
}


class AgentError(PlatformError):
    """The only exception the agent module raises.

    Every node below wraps its failure mode in this with a message
    describing what step failed - a subclass per node (``PlanningError``,
    ``ContextRetrievalError``, ...) was tried and dropped: nothing ever
    caught them differently, so the taxonomy was pure ceremony. See
    ``.claude/rules/python-style.md``.
    """


class AgentState(BaseModel):
    """State passed between nodes in the workflow below.

    Each node reads what it needs from this state and returns a partial
    update; LangGraph merges the update back in.

    Attributes:
        session_id: Conversation/session identifier.
        input: The user's latest message.
        history: Prior turns in this conversation, oldest first.
        allowed_tools: Tool names execute_tools may consider this turn.
            Empty (the default) means every registered tool is available -
            see ``_execute_tools``. A name not in the registry just means
            one less usable tool, the same as an unknown name reaching
            ``ToolRegistry.call_tool`` - not an error.
        context: Chunks retrieved by the retrieve_context node.
        tool_results: Results from tools run by the execute_tools node.
        answer: Final answer produced by generate_answer, once set.
    """

    session_id: str
    input: str
    history: list[ChatMessage] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    context: list[Chunk] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    answer: str | None = None


def _mentions_a_tool(input_text: str, tools: list[ToolDefinition]) -> bool:
    """Cheap, local pre-check for whether a tool call is even plausible.

    Matches if any word of a registered tool's name (split on ``_``, e.g.
    ``extract_pdf`` -> ``extract``, ``pdf``) appears in the input. Generic
    over whatever tools are registered - nothing here is hardcoded to
    today's specific tool set, so it doesn't need updating when a new tool
    is added.

    This is a recall-favoring heuristic, not a replacement for the LLM's
    judgment: false positives just mean execute_tools asks the LLM as
    before; a false negative skips that ask. It exists to skip the ask
    entirely (saving one full LLM round-trip) on the common turn where no
    tool is even plausible - not to second-guess the LLM when a tool name
    genuinely is referenced.
    """
    lowered = input_text.lower()
    return any(
        word in lowered for tool in tools for word in tool.name.lower().split("_") if len(word) > 2
    )


def _is_smalltalk(input_text: str) -> bool:
    """Cheap, local pre-check for whether retrieval is even worth doing.

    Exact-match only (after trimming trailing punctuation), against a small
    fixed set of greetings/acknowledgements/closings with no informational
    content - see ``_SMALLTALK_MESSAGES``. Deliberately not a substring/
    prefix match: that would also fire on "hi, what's the mongodb
    timeout?", which very much needs retrieval. Precision-
    favoring in the opposite direction from ``_mentions_a_tool``: skipping
    retrieval on a message that actually needed it just means
    ``generate_answer`` says it lacks information (see ``SYSTEM_PROMPT``)
    instead of hallucinating - safe, but wasted potential, so this only
    fires when there's essentially no doubt. Any longer or unmatched input
    still retrieves as before.
    """
    normalized = input_text.strip().lower().rstrip("!.,;: ")
    return normalized in _SMALLTALK_MESSAGES


# --- Graph -----------------------------------------------------------------


class AgentGraph:
    """Build the agent workflow from its external dependencies."""

    def __init__(
        self,
        llm: LLMProvider,
        retriever: Retriever,
        tool_registry: ToolRegistry,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._tool_registry = tool_registry

    async def _retrieve_context(self, state: AgentState) -> dict[str, Any]:
        """Fetch context chunks relevant to the current input."""
        if _is_smalltalk(state.input):
            logger.debug("[retrieve_context] session_id=%r skipped (smalltalk)", state.session_id)
            return {"context": []}
        try:
            chunks = await self._retriever.search(state.input)
        except Exception as exc:
            raise AgentError(f"Failed to retrieve context: {exc}") from exc
        logger.debug("[retrieve_context] session_id=%r chunks=%d", state.session_id, len(chunks))
        return {"context": chunks}

    async def _execute_tools(self, state: AgentState) -> dict[str, Any]:
        """Ask the LLM which tools, if any, would help, then run them."""
        tools = self._tool_registry.get_tools()
        if state.allowed_tools:
            allowed = set(state.allowed_tools)
            tools = [tool for tool in tools if tool.name in allowed]
        if not tools or not _mentions_a_tool(state.input, tools):
            logger.debug(
                "[execute_tools] session_id=%r skipped (no tool mentioned or none allowed)",
                state.session_id,
            )
            return {"tool_results": []}

        prompt = TOOL_CALL_PROMPT_TEMPLATE.format(
            system_prompt=SYSTEM_PROMPT,
            input=state.input,
            tools=format_tools(tools),
        )
        try:
            raw = await self._llm.generate(prompt, max_tokens=_TOOL_CALL_MAX_TOKENS)
        except Exception as exc:
            raise AgentError(f"Failed to decide which tools to call: {exc}") from exc

        calls = parse_tool_calls(raw)
        logger.debug(
            "[execute_tools] session_id=%r requested_calls=%d", state.session_id, len(calls)
        )
        # tools (not the full registry) is the enforcement boundary: a call
        # for anything outside it is dropped here, not just kept out of the
        # prompt - a hallucinated name that happens to exist elsewhere in
        # the registry must not slip through just because the LLM guessed it.
        allowed_names = {tool.name for tool in tools}
        results = [
            await self._tool_registry.call_tool(call["name"], call.get("arguments") or {})
            for call in calls
            if call["name"] in allowed_names
        ]
        return {"tool_results": results}

    async def _generate_answer(self, state: AgentState) -> dict[str, Any]:
        """Produce the final answer from context and tool results."""
        prompt = GENERATE_ANSWER_PROMPT_TEMPLATE.format(
            system_prompt=SYSTEM_PROMPT,
            history=format_history(state.history),
            input=state.input,
            context=format_context(state.context),
            tool_results=format_tool_results(state.tool_results),
        )
        try:
            answer = await self._llm.generate(prompt)
        except Exception as exc:
            raise AgentError(f"Failed to generate an answer: {exc}") from exc
        return {"answer": answer}

    def _build_graph(self, *, include_answer: bool) -> StateGraph:
        graph: StateGraph = StateGraph(AgentState)
        graph.add_node("retrieve_context", self._retrieve_context)
        graph.add_node("execute_tools", self._execute_tools)
        graph.add_edge(START, "retrieve_context")
        graph.add_edge(START, "execute_tools")

        if include_answer:
            graph.add_node("generate_answer", self._generate_answer)
            graph.add_edge("retrieve_context", "generate_answer")
            graph.add_edge("execute_tools", "generate_answer")
            graph.add_edge("generate_answer", END)
        else:
            graph.add_edge("retrieve_context", END)
            graph.add_edge("execute_tools", END)

        return graph

    def compile(self) -> CompiledStateGraph:
        """Compile the full workflow, ending in ``generate_answer``."""
        return self._build_graph(include_answer=True).compile()

    def compile_prefix(self) -> CompiledStateGraph:
        """Compile everything up to (not including) ``generate_answer``.

        Used by ``AgentService.run_stream`` to get ``context``/
        ``tool_results`` filled in, then render the same
        ``GENERATE_ANSWER_PROMPT_TEMPLATE`` and call the LLM itself in
        streaming mode - the final answer is the only piece of node logic
        with a legitimate second caller, so it isn't just another graph
        node.
        """
        return self._build_graph(include_answer=False).compile()
