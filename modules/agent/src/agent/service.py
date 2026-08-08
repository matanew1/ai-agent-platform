"""Agent service: the module's public entry point."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent.internal.graph import AgentError, AgentGraph, AgentState
from agent.internal.ports import (
    AgentDefinitionRepository,
    LLMProvider,
    Memory,
    Retriever,
    ToolRegistry,
)
from agent.internal.prompts import GENERATE_ANSWER_PROMPT_TEMPLATE, SYSTEM_PROMPT
from shared.prompt_formatters import format_context, format_history, format_tool_results
from shared.types import AgentDefinition, ChatMessage, SessionCheckpoint

MAX_HISTORY_MESSAGES = 40


class AgentDefinitionService:
    """Manage versioned agent configuration in caller-provided owner scopes."""

    def __init__(
        self, repository: AgentDefinitionRepository, tool_registry: ToolRegistry
    ) -> None:
        self._repository = repository
        self._tool_registry = tool_registry

    async def create(
        self, owner_id: str, name: str, system_prompt: str, allowed_tools: list[str]
    ) -> AgentDefinition:
        """Create a user-owned agent definition after validating its tools."""
        self._validate_tools(allowed_tools)
        return await self._repository.create(
            AgentDefinition(
                owner_id=owner_id,
                name=name,
                system_prompt=system_prompt,
                allowed_tools=allowed_tools,
            )
        )

    async def get(self, owner_id: str, agent_id: str) -> AgentDefinition | None:
        """Get a definition only if the requesting user owns it."""
        return await self._repository.get(owner_id, agent_id)

    async def list(self, owner_id: str) -> list[AgentDefinition]:
        """List all definitions owned by one user."""
        return await self._repository.list(owner_id)

    async def update(
        self,
        owner_id: str,
        agent_id: str,
        *,
        name: str | None = None,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> AgentDefinition | None:
        """Apply a partial update and increment the definition version."""
        definition = await self._repository.get(owner_id, agent_id)
        if definition is None:
            return None
        if allowed_tools is not None:
            self._validate_tools(allowed_tools)

        changes = {
            key: value
            for key, value in {
                "name": name,
                "system_prompt": system_prompt,
                "allowed_tools": allowed_tools,
            }.items()
            if value is not None
        }
        if not changes:
            return definition
        updated = definition.model_copy(
            update={
                **changes,
                "version": definition.version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.save(updated)
        return updated

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        """Delete a definition only if the user owns it."""
        return await self._repository.delete(owner_id, agent_id)

    def _validate_tools(self, allowed_tools: list[str]) -> None:
        """Reject duplicate and unavailable tools before saving configuration."""
        duplicates = {name for name in allowed_tools if allowed_tools.count(name) > 1}
        if duplicates:
            raise ValueError(f"Duplicate tool names are not allowed: {sorted(duplicates)}")
        registered_tools = {tool.name for tool in self._tool_registry.get_tools()}
        unknown_tools = sorted(set(allowed_tools) - registered_tools)
        if unknown_tools:
            raise ValueError(f"Unknown tool names: {unknown_tools}")


@dataclass
class AgentTurnResult:
    """Everything about one completed ``run()`` turn, not just the reply text.

    ``run()``'s own domain type, not ``agent.api.schemas.ChatResponse`` -
    the API schema is built from this in ``agent.api.router.chat``,
    keeping the internal shape separate from the response model per
    ``.claude/rules/api-conventions.md``.

    Attributes:
        answer: The generated reply.
        execution_time_seconds: Wall-clock time for the whole turn -
            session lock wait, history load, the graph run, and the save
            back to memory. What a caller actually experienced, not just
            the LLM's own generation time.
        tools_invoked: Name of every tool ``execute_tools`` called, in
            call order - including one that failed
            (``ToolResult.is_error``); "invoked" means called, not
            "succeeded". Empty when the turn needed no tools.
        chunks_retrieved: How many chunks ``retrieve_context`` got back
            from the retriever. ``0`` both when retrieval found nothing
            and when it was skipped outright (smalltalk) - ``run()`` has
            no way to distinguish those from the graph's final state, and
            a caller mainly wants to know "did any context back this
            answer", for which the two are the same answer: no.
    """

    answer: str
    execution_time_seconds: float
    tools_invoked: list[str] = field(default_factory=list)
    chunks_retrieved: int = 0


@dataclass
class ChatStreamMetadata:
    """Known before ``run_stream``'s answer starts streaming - see its docstring.

    Attributes:
        tools_invoked: Same meaning as ``AgentTurnResult.tools_invoked``.
        chunks_retrieved: Same meaning as ``AgentTurnResult.chunks_retrieved``.
        prep_time_seconds: Time for session lock wait + history load +
            retrieve_context/execute_tools - everything before the answer
            itself starts generating. Not the whole turn's time the way
            ``AgentTurnResult.execution_time_seconds`` is: a total isn't
            knowable until the stream ends, and by then the client has
            already received the full answer and can time that itself -
            what it can't derive on its own is which tools ran or how much
            context backed the answer, which is what this is actually for.
    """

    tools_invoked: list[str]
    chunks_retrieved: int
    prep_time_seconds: float


class AgentService:
    """Coordinates the AI agent execution flow.

    Responsibilities:
        - Execute the LangGraph workflow (retrieve_context ∥ execute_tools ->
          generate_answer).
        - Load prior conversation history via ``memory`` before a turn and
          save it back, with the new turn appended, after.
        - Give the graph access to retrieval (``retriever``) and tools
          (``tool_registry``) - the graph nodes call them, not callers of
          this service.

    Args:
        llm: Language model provider.
        retriever: RAG retrieval service.
        memory: Session checkpoint store.
        tool_registry: Registry of tools available to the agent.
    """

    def __init__(
        self,
        llm: LLMProvider,
        retriever: Retriever,
        memory: Memory,
        tool_registry: ToolRegistry,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self._memory = memory
        self._llm = llm
        # Two compiled forms of the same workflow, built once here (never
        # per-request - see .claude/rules/architecture.md, dependency
        # injection): the full graph for run(), and everything up to (not
        # including) generate_answer for run_stream(), which makes that
        # last LLM call itself in streaming mode - see AgentGraph's
        # docstring for why that one step isn't just another graph node.
        self._system_prompt = system_prompt
        self._agent_graph = AgentGraph(
            llm=llm,
            retriever=retriever,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
        )
        self._graph = self._agent_graph.compile()
        self._prefix_graph = self._agent_graph.compile_prefix()

    async def _load_history(self, session_id: str) -> list[ChatMessage]:
        checkpoint = await self._memory.get_checkpoint(session_id)
        return (checkpoint.history if checkpoint else [])[-MAX_HISTORY_MESSAGES:]

    async def _save_turn(
        self, session_id: str, history: list[ChatMessage], message: str, answer: str
    ) -> None:
        new_history = [
            *history,
            ChatMessage(role="user", content=message),
            ChatMessage(role="assistant", content=answer),
        ][-MAX_HISTORY_MESSAGES:]
        await self._memory.save_checkpoint(
            SessionCheckpoint(session_id=session_id, history=new_history)
        )

    async def run(
        self, session_id: str, message: str, tools: list[str] | None = None
    ) -> AgentTurnResult:
        """Run one turn and save it to the session history.

        The whole load -> run workflow -> save sequence runs under
        ``memory.session_lock(session_id)`` - without it, two concurrent
        requests on the same session_id could both read the same starting
        history and then both save, with whichever save lands last
        silently dropping the other's turn. Different sessions never
        contend with each other's lock, so this doesn't serialize
        unrelated traffic. Timed from here, so the lock wait counts too -
        see ``AgentTurnResult.execution_time_seconds``.

        Args:
            session_id: Conversation/session identifier.
            message: The user's message.
            tools: Restrict ``execute_tools`` to these tool names for this
                turn. ``None`` or empty (the default) leaves every
                registered tool available - see
                ``agent.internal.graph.AgentState.allowed_tools``.
        """
        start = time.monotonic()
        async with self._memory.session_lock(session_id):
            history = await self._load_history(session_id)

            result = await self._graph.ainvoke(
                AgentState(
                    session_id=session_id,
                    input=message,
                    history=history,
                    allowed_tools=tools or [],
                )
            )
            answer = result.get("answer") if isinstance(result, dict) else None
            if not answer:
                raise AgentError(f"Agent workflow produced no answer for session {session_id!r}.")

            await self._save_turn(session_id, history, message, answer)

        return AgentTurnResult(
            answer=answer,
            execution_time_seconds=time.monotonic() - start,
            tools_invoked=[tool_result.tool_name for tool_result in result.get("tool_results", [])],
            chunks_retrieved=len(result.get("context", [])),
        )

    async def run_stream(
        self, session_id: str, message: str, tools: list[str] | None = None
    ) -> tuple[ChatStreamMetadata, AsyncIterator[str]]:
        """Run one turn, returning metadata immediately and the answer as a stream.

        Args:
            session_id: Conversation/session identifier.
            message: The user's message.
            tools: Same meaning as ``run``'s ``tools`` - restricts
                ``execute_tools`` to these names for this turn, or leaves
                every registered tool available if ``None``/empty.

        Split into two return values - rather than a single async
        generator, which is what this was before ``ChatStreamMetadata``
        existed - because ``tools_invoked``/``chunks_retrieved`` are only
        useful to a caller as HTTP response headers (see
        ``agent.api.router.chat_stream``), and headers must be sent
        before any body bytes go out. That forces the metadata to be
        fully known before the answer starts streaming, which is exactly
        when it *is* known: ``retrieve_context``/``execute_tools`` (via
        ``compile_prefix()``) already run to completion before
        ``generate_answer``'s streaming call starts, same as they always
        did here.

        One real trade-off from the split: the HTTP response (headers
        included) no longer starts until this prep phase finishes,
        whereas before, headers could go out while prep was still
        running. In practice this is imperceptible - no realistic client
        treats "headers arrived" as a user-visible event distinct from
        "the first byte of the answer arrived," which was already gated
        on prep completing either way (see the module's existing "still
        has to finish first, same as POST /chat" note in
        ``agent.api.router.chat_stream``).

        ``memory.session_lock(session_id)`` still spans the *whole* turn
        - prep here and the streaming/save in the returned generator -
        for the same reason ``run()`` holds it continuously. Since that
        now crosses this method's own return, the lock is entered
        manually (``AsyncExitStack``, not ``async with``) and closed
        inside the generator's ``finally``. That means the returned
        generator must actually be consumed (or explicitly closed) or
        the lock leaks - true of the one real caller,
        ``agent.api.router.chat_stream``, which immediately hands it to
        ``StreamingResponse`` and Starlette guarantees will drain or
        close it either way, including on an early client disconnect.

        Raises:
            AgentError: If ``retrieve_context``/``execute_tools`` fails
                during prep, before any metadata or stream is returned.
        """
        start = time.monotonic()
        exit_stack = AsyncExitStack()
        await exit_stack.enter_async_context(self._memory.session_lock(session_id))
        try:
            history = await self._load_history(session_id)
            prefix_result = await self._prefix_graph.ainvoke(
                AgentState(
                    session_id=session_id, input=message, history=history, allowed_tools=tools or []
                )
            )
        except BaseException:
            # Broad on purpose (not just Exception) - this must run on
            # cancellation too, or a client disconnect during prep leaks
            # the lock. Always re-raised, never swallowed.
            await exit_stack.aclose()
            raise

        metadata = ChatStreamMetadata(
            tools_invoked=[
                tool_result.tool_name for tool_result in prefix_result.get("tool_results", [])
            ],
            chunks_retrieved=len(prefix_result.get("context", [])),
            prep_time_seconds=time.monotonic() - start,
        )
        # Same GENERATE_ANSWER_PROMPT_TEMPLATE/formatters as
        # AgentGraph._generate_answer - duplicated here (not exposed as a
        # method on AgentGraph) so the graph doesn't have to carry a public
        # surface that exists for exactly one external caller.
        prompt = GENERATE_ANSWER_PROMPT_TEMPLATE.format(
                system_prompt=self._system_prompt,
            history=format_history(history),
            input=message,
            context=format_context(prefix_result.get("context", [])),
            tool_results=format_tool_results(prefix_result.get("tool_results", [])),
        )

        async def _stream_answer() -> AsyncIterator[str]:
            chunks: list[str] = []
            try:
                async for chunk in self._llm.generate_stream(prompt):
                    chunks.append(chunk)
                    yield chunk
            except Exception as exc:
                raise AgentError(f"Failed to generate an answer: {exc}") from exc
            finally:
                answer = "".join(chunks)
                if answer:
                    await self._save_turn(session_id, history, message, answer)
                await exit_stack.aclose()

        return metadata, _stream_answer()
