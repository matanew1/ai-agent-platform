"""The LangGraph workflow: the graph itself, and its error type.

    START -> retrieve_context -> execute_tools -> END

Tool execution deliberately follows retrieval. Generation tools need the
retrieved material and conversation history to create the requested artifact;
running those branches in parallel left the tool chooser staring only at raw
requests such as "generate a PDF about him" with no way to resolve either the
pronoun or the document body. ``AgentService`` uses the completed state to
render the final-answer prompt and stream it.
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

State lives in ``graph.state``, prompt templates in ``graph.prompt``. Both
external dependencies - retrieval and tools - are typed against their one
concrete implementation directly (``OwnerScopedRetriever``/
``rag.service.RAGService`` below, and ``tool.service.ToolService``) rather
than a ``Protocol`` port: neither has a second implementation to justify
one - see ``.claude/rules/architecture.md``'s "Avoiding over-engineering".
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from graph.prompt import (
    GENERATE_ARTIFACT_CONTENT_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
    TOOL_CALL_PROMPT_TEMPLATE,
)
from graph.state import AgentState
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from rag.service import RAGService
from tool.service import ToolService

from infrastructure.llm.protocol import LanguageModelClient
from shared.prompt_formatters import (
    format_attachments,
    format_context,
    format_history,
    format_tools,
)
from shared.tool_calls import parse_tool_calls
from shared.types import Chunk, PlatformError, ToolDefinition

logger = logging.getLogger(__name__)

# --- Decision-call tuning ----------------------------------------------------

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
# failure either way: infrastructure.llm.ollama's _require_content raises
# instead of returning the empty string that used to parse into zero tool
# calls.
_TOOL_CALL_MAX_TOKENS = 200

# Smalltalk/acknowledgement messages with no informational content - see
# _is_smalltalk below. Kept as an exact-match set (not substring/prefix
# matching): a prefix match on "hi" would also match "hi, what's the
# database timeout?", which very much needs retrieval.
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


# --- Errors --------------------------------------------------------------------


class AgentError(PlatformError):
    """The only exception the agent workflow raises.

    Every node below wraps its failure mode in this with a message
    describing what step failed - a subclass per node (``PlanningError``,
    ``ContextRetrievalError``, ...) was tried and dropped: nothing ever
    caught them differently, so the taxonomy was pure ceremony. See
    ``.claude/rules/python-style.md``.
    """


async def handle_agent_error(request: Request, exc: AgentError) -> JSONResponse:
    """Map agent-workflow failures to a consistent error response shape.

    Registered from ``app/main.py`` via ``app.add_exception_handler`` -
    colocated with ``AgentError`` here rather than a shared handler module,
    since it's the only thing that raises this type. No raw internal
    exception ever reaches the client - see
    ``.claude/rules/api-conventions.md``.
    """
    logger.warning("Agent workflow failed: %s", exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# --- Heuristics ---------------------------------------------------------------


def _mentions_a_tool(input_text: str, tools: list[ToolDefinition]) -> bool:
    """Cheap, local pre-check for whether a tool call is even plausible.

    Matches if any word of a registered tool's name (split on ``_``, e.g.
    ``extract_pdf`` -> ``extract``, ``pdf``) *or* its source (e.g. ``gmail``,
    ``tavily``, ``fetch`` - see ``ToolDefinition.source``) appears in the
    input. Generic over whatever tools are registered - nothing here is
    hardcoded to today's specific tool set, so it doesn't need updating when
    a new tool is added.

    The source half of this matters because a tool's own name doesn't
    always contain the product name a user would actually type: every
    Gmail tool is named around ``email`` (``search_emails``, ``read_email``,
    ...), so "show me my last 10 gmails" - a completely ordinary way to
    phrase that request - matched none of them and skipped tool execution
    entirely, before this was added. ``tool.source`` is exactly the
    registered MCP server's name (``mcp-servers.yaml``'s key), so checking
    it too closes this gap the same generic way for any future server, not
    just gmail - except for ``"local"`` itself, ``ToolDefinition.source``'s
    default for every in-process tool (``pdf``, ``markdown``, ``ats``, ...).
    Unlike a real MCP server name, ``"local"`` is a generic English word
    with no relation to what any tool actually does, and local tools are
    always registered - so treating it as a keyword the same way as
    ``"gmail"`` made this fire on ordinary, unrelated messages ("a good
    local restaurant", "saved it locally") on effectively every turn,
    defeating the whole point of a pre-check meant to skip the LLM ask when
    no tool is plausible. Excluded explicitly below.

    This is a recall-favoring heuristic, not a replacement for the LLM's
    judgment: false positives just mean execute_tools asks the LLM as
    before; a false negative skips that ask. It exists to skip the ask
    entirely (saving one full LLM round-trip) on the common turn where no
    tool is even plausible - not to second-guess the LLM when a tool name
    genuinely is referenced.
    """
    lowered = input_text.lower()
    words = {
        word
        for tool in tools
        for text in (tool.name, tool.source)
        if text != "local"
        for word in text.lower().split("_")
        if len(word) > 2
    }
    return any(word in lowered for word in words)


def _explicitly_named_tools(input_text: str, tools: list[ToolDefinition]) -> list[ToolDefinition]:
    """Return tools whose full names the user explicitly included in their request.

    The routing prompt can become very large when an agent is authorized for
    several MCP servers. If the user already names a tool (for example,
    ``search_emails``), presenting the whole registry makes a simple,
    unambiguous request needlessly difficult for smaller local models. Keep
    only the named tools for that decision; authorization is still enforced
    by the caller's already-filtered ``tools`` list.
    """
    lowered = input_text.lower()
    return [tool for tool in tools if tool.name.lower() in lowered]


_GMAIL_INBOX_WORDS = frozenset(
    {"email", "emails", "mail", "inbox", "unread", "message", "messages"}
)
_GMAIL_READ_ONLY_WORDS = frozenset({"search", "find", "read", "summarize", "summary"})
# Checked before the topic/action words below and wins outright: "unread"/
# "inbox" are topic words describing *what* mail, not what to do with it, so
# a request like "delete my unread emails" or "archive all messages in my
# inbox" satisfies both word sets on topic alone. Narrowing the routing
# prompt down to search_emails/read_email for such a request wouldn't just
# fail to help - it would make delete_email/modify_email/batch_delete_emails
# structurally unselectable, since their schemas would never reach the
# prompt at all. Word-*set* membership matters here, not substring
# containment: "read" is a literal substring of "unread", so a naive
# `"read" in text` check would misfire on exactly the mutating requests this
# list exists to exclude - see _gmail_inbox_tools' tokenization below.
_GMAIL_MUTATING_WORDS = frozenset(
    {
        "delete",
        "remove",
        "archive",
        "mark",
        "label",
        "move",
        "trash",
        "modify",
        "send",
        "draft",
        "reply",
        "forward",
        "unsubscribe",
    }
)


def _gmail_inbox_tools(input_text: str, tools: list[ToolDefinition]) -> list[ToolDefinition]:
    """Pick the two Gmail tools needed to inspect an inbox-style request.

    Searching unread mail and reading the matching messages are a common
    two-step task. Limiting the routing menu to these tools keeps their
    schemas visible to smaller local models instead of burying them among
    every enabled MCP capability. Mutating Gmail requests intentionally do
    not use this shortcut and retain the normal decision flow - see
    ``_GMAIL_MUTATING_WORDS``.
    """
    words = set(re.findall(r"[a-z0-9]+", input_text.lower()))
    if words & _GMAIL_MUTATING_WORDS:
        return []
    if not (words & _GMAIL_INBOX_WORDS) or not (words & _GMAIL_READ_ONLY_WORDS):
        return []
    inbox_tool_names = {"search_emails", "read_email"}
    return [tool for tool in tools if tool.name in inbox_tool_names]


def _is_smalltalk(input_text: str) -> bool:
    """Cheap, local pre-check for whether retrieval is even worth doing.

    Exact-match only (after trimming trailing punctuation), against a small
    fixed set of greetings/acknowledgements/closings with no informational
    content - see ``_SMALLTALK_MESSAGES``. Deliberately not a substring/
    prefix match: that would also fire on "hi, what's the database
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


def _requested_artifact(input_text: str) -> tuple[str, str, str] | None:
    """Return ``(tool_name, content_argument, format)`` for explicit file creation.

    This narrow deterministic branch handles operations whose complete
    document body cannot fit inside the small JSON tool-selection budget.
    Every non-generation tool still goes through the model's normal selector.
    """
    lowered = input_text.lower()
    asks_to_create = any(
        verb in lowered
        for verb in (
            "create",
            "generate",
            "genereate",
            "genrate",
            "make",
            "write",
            "build",
            "produce",
            "export",
            "download",
        )
    )
    if not asks_to_create:
        return None
    if "pdf" in lowered or ".pdf" in lowered:
        return ("generate_pdf", "text", "Markdown-formatted PDF")
    if "markdown" in lowered or ".md" in lowered:
        return ("generate_markdown", "content", "Markdown")
    return None


# --- Retrieval -----------------------------------------------------------------


class OwnerScopedRetriever:
    """Retrieval scoped to one owner's document library.

    Documents belong to an owner (a future userID), not to a specific
    agent - see ``rag.controller``'s ``documents_router``. Every agent that
    owner_id owns shares the same pool, so this only needs owner_id, not an
    agent_id. Built fresh per turn by ``chat.service.build_chat_service``
    and handed to ``AgentGraph``/``ChatService`` as their only retrieval
    dependency.
    """

    def __init__(self, retriever: RAGService, owner_id: str) -> None:
        self._retriever = retriever
        self._metadata_filter = {"owner_id": owner_id}

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Return only chunks indexed for this owner."""
        return await self._retriever.search(query, top_k, metadata_filter=self._metadata_filter)


# --- Graph ---------------------------------------------------------------------


class AgentGraph:
    """Build the agent workflow from its external dependencies."""

    def __init__(
        self,
        llm: LanguageModelClient,
        retriever: OwnerScopedRetriever,
        tool_registry: ToolService,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._tool_registry = tool_registry
        self._system_prompt = system_prompt

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
        registered_names = {tool.name for tool in tools}
        artifact_request = _requested_artifact(state.input)
        if artifact_request and artifact_request[0] not in registered_names:
            raise AgentError(f"Requested artifact tool {artifact_request[0]!r} is not registered.")
        # None means "no restriction" (an agent with an empty allowed_tools
        # is itself unrestricted, see shared.tools's docstring); an empty
        # *list* is a caller deliberately narrowing to zero tools (e.g. a
        # schedule/chat tools override, see chat.controller/
        # automation.runner) and must actually filter everything out, not
        # be treated the same as "no restriction" via a truthy check - that
        # was a real bug (an explicit tools=[] silently granted every
        # registered tool instead of none).
        if state.allowed_tools is not None:
            allowed = set(state.allowed_tools)
            tools = [tool for tool in tools if tool.name in allowed]
            if artifact_request and artifact_request[0] not in allowed:
                raise AgentError(
                    f"Tool {artifact_request[0]!r} is disabled for this agent. "
                    "Enable it under Allowed tools and try again."
                )
        if not tools:
            logger.debug(
                "[execute_tools] session_id=%r skipped (no tools allowed)", state.session_id
            )
            return {"tool_results": []}

        allowed_names = {tool.name for tool in tools}
        if artifact_request and artifact_request[0] in allowed_names:
            tool_name, content_argument, artifact_format = artifact_request
            content_prompt = GENERATE_ARTIFACT_CONTENT_PROMPT_TEMPLATE.format(
                system_prompt=self._system_prompt,
                history=format_history(state.history),
                input=state.input,
                attachments=format_attachments(state.attachments),
                context=format_context(state.context),
                artifact_format=artifact_format,
            )
            try:
                # Artifact bodies can be much larger than a compact JSON
                # routing decision, so leave this generation uncapped and
                # pass the finished body directly to the renderer.
                content = await self._llm.generate(content_prompt)
            except Exception as exc:
                raise AgentError(f"Failed to compose the requested artifact: {exc}") from exc
            result = await self._tool_registry.call_tool(
                tool_name,
                {content_argument: content},
            )
            return {"tool_results": [result]}

        recent_history = "\n".join(message.content for message in state.history[-2:])
        mention_text = f"{recent_history}\n{state.input}" if recent_history else state.input
        if not _mentions_a_tool(mention_text, tools):
            logger.debug(
                "[execute_tools] session_id=%r skipped (no tool mentioned or none allowed)",
                state.session_id,
            )
            return {"tool_results": []}

        routing_tools = _explicitly_named_tools(state.input, tools) or _gmail_inbox_tools(
            state.input, tools
        )
        if routing_tools:
            tools = routing_tools
            allowed_names = {tool.name for tool in tools}
            logger.debug(
                "[execute_tools] session_id=%r narrowed_to_routing_tools=%s",
                state.session_id,
                sorted(allowed_names),
            )

        prompt = TOOL_CALL_PROMPT_TEMPLATE.format(
            system_prompt=self._system_prompt,
            history=format_history(state.history),
            input=state.input,
            attachments=format_attachments(state.attachments),
            context=format_context(state.context),
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
        results = [
            await self._tool_registry.call_tool(call["name"], call.get("arguments") or {})
            for call in calls
            if call["name"] in allowed_names
        ]
        return {"tool_results": results}

    def _build_graph(self) -> StateGraph:
        graph: StateGraph = StateGraph(AgentState)
        graph.add_node("retrieve_context", self._retrieve_context)
        graph.add_node("execute_tools", self._execute_tools)
        graph.add_edge(START, "retrieve_context")
        graph.add_edge("retrieve_context", "execute_tools")
        graph.add_edge("execute_tools", END)

        return graph

    def compile_prefix(self) -> CompiledStateGraph:
        """Compile the retrieval and tool-execution preparation graph."""
        return self._build_graph().compile()


__all__ = ["AgentError", "AgentGraph", "OwnerScopedRetriever", "handle_agent_error"]
