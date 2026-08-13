"""Agent turn execution: the module's core service."""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from graph.graph import AgentError, AgentGraph, OwnerScopedRetriever
from graph.prompt import GENERATE_ANSWER_PROMPT_TEMPLATE, SYSTEM_PROMPT
from graph.state import AgentState
from session.service import HybridSessionStore
from tool.service import ToolService

from infrastructure.llm.protocol import LanguageModelClient
from shared.prompt_formatters import (
    format_attachments,
    format_context,
    format_history,
    format_tool_results,
)
from shared.types import (
    ArtifactReference,
    ChatMessage,
    RetrievedSource,
    SessionCheckpoint,
    ToolResult,
)

MAX_HISTORY_MESSAGES = 40


@dataclass
class ChatStreamMetadata:
    """Known before ``run_stream``'s answer starts streaming - see its docstring.

    Attributes:
        tools_invoked: Names of tools called during the preparation phase.
        chunks_retrieved: Number of context chunks retrieved during preparation.
        prep_time_seconds: Time for session lock wait, history load, and
            retrieve_context/execute_tools. A total isn't knowable until
            the stream ends, and by then the client has
            already received the full answer and can time that itself -
            what it can't derive on its own is which tools ran or how much
            context backed the answer, which is what this is actually for.
        artifacts: Download metadata returned by successful generation/editing tools.
    """

    tools_invoked: list[str]
    chunks_retrieved: int
    prep_time_seconds: float
    artifacts: list[ArtifactReference] = field(default_factory=list)
    sources: list[RetrievedSource] = field(default_factory=list)


def _artifact_references(tool_results: list[ToolResult]) -> list[ArtifactReference]:
    """Extract safe public artifact metadata from successful tool results."""
    artifacts: list[ArtifactReference] = []
    for result in tool_results:
        if result.is_error or not isinstance(result.content, dict):
            continue
        filename = result.content.get("filename")
        download_url = result.content.get("download_url")
        if isinstance(filename, str) and isinstance(download_url, str):
            artifacts.append(ArtifactReference(filename=filename, download_url=download_url))
    return artifacts


def _retrieved_sources(chunks: list[object]) -> list[RetrievedSource]:
    """Reduce retrieved chunks to safe evidence cards for the client."""
    sources: list[RetrievedSource] = []
    for chunk in chunks:
        metadata = getattr(chunk, "metadata", {})
        source_id = (
            metadata.get("source_id", "Document") if isinstance(metadata, dict) else "Document"
        )
        display_id = source_id.partition(":")[2] or source_id
        # Chat uploads have an internal, collision-safe source ID such as
        # ``chat/<agent-id>/<content-hash>-resume.pdf``. It must remain in
        # RAG metadata, but citations only need the human-facing filename.
        if display_id.startswith("chat/"):
            display_id = display_id.rsplit("/", 1)[-1]
            display_id = re.sub(r"^[0-9a-f]{16}-", "", display_id, flags=re.IGNORECASE)
        excerpt = " ".join(str(getattr(chunk, "text", "")).split())[:280]
        if excerpt:
            sources.append(
                RetrievedSource(
                    source_id=display_id, excerpt=excerpt, score=float(getattr(chunk, "score", 0))
                )
            )
    return sources


class ChatService:
    """Coordinates one conversational turn through the LangGraph workflow.

    Responsibilities:
        - Execute the LangGraph workflow (retrieve_context -> execute_tools ->
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
        llm: LanguageModelClient,
        retriever: OwnerScopedRetriever,
        memory: HybridSessionStore,
        tool_registry: ToolService,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self._memory = memory
        self._llm = llm
        # The preparation graph is compiled once here, never per request.
        # The final LLM call is intentionally outside LangGraph so its
        # output can be streamed directly to the client.
        self._system_prompt = system_prompt
        self._agent_graph = AgentGraph(
            llm=llm,
            retriever=retriever,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
        )
        self._prefix_graph = self._agent_graph.compile_prefix()

    async def _load_history(self, session_id: str) -> list[ChatMessage]:
        checkpoint = await self._memory.get_checkpoint(session_id)
        return (checkpoint.history if checkpoint else [])[-MAX_HISTORY_MESSAGES:]

    async def _save_turn(
        self,
        session_id: str,
        history: list[ChatMessage],
        message: str,
        answer: str,
        metadata: ChatStreamMetadata,
    ) -> None:
        new_history = [
            *history,
            ChatMessage(role="user", content=message),
            ChatMessage(
                role="assistant",
                content=answer,
                tools_invoked=metadata.tools_invoked,
                chunks_retrieved=metadata.chunks_retrieved,
                prep_time_seconds=metadata.prep_time_seconds,
                artifacts=metadata.artifacts,
                sources=metadata.sources,
            ),
        ][-MAX_HISTORY_MESSAGES:]
        await self._memory.save_checkpoint(
            SessionCheckpoint(session_id=session_id, history=new_history)
        )

    async def run_stream(
        self,
        session_id: str,
        message: str,
        tools: list[str] | None = None,
        attachments: list[tuple[str, str]] | None = None,
    ) -> tuple[ChatStreamMetadata, AsyncIterator[str]]:
        """Run one turn, returning metadata immediately and the answer as a stream.

        Args:
            session_id: Conversation/session identifier.
            message: The user's message.
            tools: Restricts ``execute_tools`` to these names for this
                turn, or leaves every registered tool available if
                ``None``/empty.
            attachments: ``(filename, extracted_text)`` pairs for files
                attached to this turn only (see ``chat.controller``'s chat
                route). Folded into the answer prompt but never into
                ``message`` - so they're never written to conversation
                history via ``_save_turn``. They are available during this
                turn's tool preparation, including artifact creation.
                Genuinely ephemeral: gone once this
                turn's answer is generated, not ingested into the document
                store the way ``POST /documents``'s ingestion routes are.

        Split into two return values - rather than a single async
        generator, which is what this was before ``ChatStreamMetadata``
        existed - because ``tools_invoked``/``chunks_retrieved`` are only
        useful to a caller as HTTP response headers (see
        the public API route), and headers must be sent
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
        on prep completing either way.

        ``memory.session_lock(session_id)`` spans the *whole* turn - prep
        here and the streaming/save in the returned generator - so two
        concurrent requests on the same session can't race (see
        ``session.service.HybridSessionStore.session_lock``).
        Since that spans this method's own return, the lock is entered
        manually (``AsyncExitStack``, not ``async with``) and closed
        inside the generator's ``finally``. That means the returned
        generator must actually be consumed (or explicitly closed) or
        the lock leaks - true of the one real caller,
        the public API route, which immediately hands it to
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
                    session_id=session_id,
                    input=message,
                    history=history,
                    attachments=attachments or [],
                    allowed_tools=tools or [],
                )
            )
        except BaseException:
            # Broad on purpose (not just Exception) - this must run on
            # cancellation too, or a client disconnect during prep leaks
            # the lock. Always re-raised, never swallowed.
            await exit_stack.aclose()
            raise

        tool_results = prefix_result.get("tool_results", [])
        context = prefix_result.get("context", [])
        metadata = ChatStreamMetadata(
            tools_invoked=[tool_result.tool_name for tool_result in tool_results],
            chunks_retrieved=len(prefix_result.get("context", [])),
            prep_time_seconds=time.monotonic() - start,
            artifacts=_artifact_references(tool_results),
            sources=_retrieved_sources(context),
        )
        # Same GENERATE_ANSWER_PROMPT_TEMPLATE/formatters as
        # AgentGraph._generate_answer - duplicated here (not exposed as a
        # method on AgentGraph) so the graph doesn't have to carry a public
        # surface that exists for exactly one external caller.
        prompt = GENERATE_ANSWER_PROMPT_TEMPLATE.format(
            system_prompt=self._system_prompt,
            history=format_history(history),
            input=message,
            attachments=format_attachments(attachments or []),
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
                    await self._save_turn(session_id, history, message, answer, metadata)
                await exit_stack.aclose()

        return metadata, _stream_answer()


__all__ = ["ChatService", "ChatStreamMetadata"]
