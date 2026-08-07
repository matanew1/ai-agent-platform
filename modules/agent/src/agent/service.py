"""Agent service: the module's public entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator

from agent.internal.graph import AgentError, AgentGraph, AgentState
from agent.internal.ports import LLMProvider, Memory, Retriever, ToolRegistry
from agent.internal.prompts import GENERATE_ANSWER_PROMPT_TEMPLATE, SYSTEM_PROMPT
from shared.prompt_formatters import format_context, format_history, format_tool_results
from shared.types import ChatMessage, SessionCheckpoint

MAX_HISTORY_MESSAGES = 40


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
    ) -> None:
        self._memory = memory
        self._llm = llm
        # Two compiled forms of the same workflow, built once here (never
        # per-request - see .claude/rules/architecture.md, dependency
        # injection): the full graph for run(), and everything up to (not
        # including) generate_answer for run_stream(), which makes that
        # last LLM call itself in streaming mode - see AgentGraph's
        # docstring for why that one step isn't just another graph node.
        self._agent_graph = AgentGraph(llm=llm, retriever=retriever, tool_registry=tool_registry)
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

    async def run(self, session_id: str, message: str) -> str:
        """Run one turn and save it to the session history.

        The whole load -> run workflow -> save sequence runs under
        ``memory.session_lock(session_id)`` - without it, two concurrent
        requests on the same session_id could both read the same starting
        history and then both save, with whichever save lands last
        silently dropping the other's turn. Different sessions never
        contend with each other's lock, so this doesn't serialize
        unrelated traffic.
        """
        async with self._memory.session_lock(session_id):
            history = await self._load_history(session_id)

            result = await self._graph.ainvoke(
                AgentState(session_id=session_id, input=message, history=history)
            )
            answer = result.get("answer") if isinstance(result, dict) else None
            if not answer:
                raise AgentError(f"Agent workflow produced no answer for session {session_id!r}.")

            await self._save_turn(session_id, history, message, answer)
        return answer

    async def run_stream(self, session_id: str, message: str) -> AsyncIterator[str]:
        """Run one turn, yielding the final answer as it's generated.

        ``retrieve_context``/``execute_tools`` run exactly as
        in ``run()`` (via ``compile_prefix()``); only ``generate_answer``'s
        LLM call is made in streaming mode, since that's the only output a
        client is actually waiting to see build up incrementally. History
        is loaded the same way as ``run()`` and saved once the stream ends
        - see ``agent.api.router``'s ``POST /chat/stream``. Held under
        ``memory.session_lock(session_id)`` for the same reason as
        ``run()`` - the lock spans every ``yield`` below too, releasing
        once the stream (and the save in ``finally``) is done.
        """
        async with self._memory.session_lock(session_id):
            history = await self._load_history(session_id)

            prefix_result = await self._prefix_graph.ainvoke(
                AgentState(session_id=session_id, input=message, history=history)
            )
            # Same GENERATE_ANSWER_PROMPT_TEMPLATE/formatters as
            # AgentGraph._generate_answer - duplicated here (not exposed as a
            # method on AgentGraph) so the graph doesn't have to carry a public
            # surface that exists for exactly one external caller.
            prompt = GENERATE_ANSWER_PROMPT_TEMPLATE.format(
                system_prompt=SYSTEM_PROMPT,
                history=format_history(history),
                input=message,
                context=format_context(prefix_result.get("context", [])),
                tool_results=format_tool_results(prefix_result.get("tool_results", [])),
            )

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
