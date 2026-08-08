"""Ports (abstractions) that the agent module depends on.

Per ``.claude/rules/architecture.md``, a module depends on interfaces it
owns, not on concrete infrastructure. Everything below is a
``typing.Protocol`` - structural typing, so ``infrastructure/*`` classes
satisfy these without importing or inheriting from them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from shared.types import Chunk, SessionCheckpoint, ToolDefinition, ToolResult


class LLMProvider(Protocol):
    """A language model capable of generating text from a prompt."""

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate a completion for a prompt.

        Args:
            prompt: Fully-rendered prompt text.
            max_tokens: Cap on the number of tokens to generate, for
                decision-only calls that never need a long answer (a
                routing choice, a JSON tool-call array). ``None`` (the
                default) leaves it uncapped - what ``generate_answer``
                wants, since it produces the actual user-facing reply.

        Returns:
            The model's response text.
        """
        ...

    def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        """Generate a completion for a prompt, yielding it token-by-token.

        Used only by ``AgentService.run_stream`` -
        every other caller (the graph's nodes) wants the full string back
        from ``generate`` and would gain nothing from streaming it. See
        ``.claude/rules/api-conventions.md`` on why streaming gets its own
        endpoint rather than a flag on a normal chat request.

        Args:
            prompt: Fully-rendered prompt text.

        Yields:
            Successive text chunks that concatenate to the full response.
        """
        ...


class Retriever(Protocol):
    """RAG retrieval capability, as consumed by the agent."""

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Find chunks relevant to a query.

        Args:
            query: Natural-language query.
            top_k: Maximum number of chunks to return.

        Returns:
            Relevant chunks, most relevant first.
        """
        ...


class ToolRegistry(Protocol):
    """Tool discovery and execution, as consumed by the agent.

    The agent never knows a tool's implementation - it only calls by name
    and gets a typed result back. See ``.claude/rules/tool-conventions.md``.
    """

    def get_tools(self) -> list[ToolDefinition]:
        """List tools currently available to the agent."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        """Execute a tool by name.

        Never raises for an unknown name or a failing handler - both come
        back as ``ToolResult(is_error=True, ...)``, since the caller is
        typically an LLM's freeform tool choice, not a hardcoded call.

        Args:
            name: Tool name, as returned by ``get_tools``.
            arguments: Arguments matching the tool's declared parameters.

        Returns:
            The tool's result.
        """
        ...


class Memory(Protocol):
    """Session checkpoint persistence, as consumed by the agent."""

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        """Fetch the stored checkpoint for a session, if any."""
        ...

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        """Persist a session checkpoint."""
        ...

    def session_lock(self, session_id: str) -> AbstractAsyncContextManager[None]:
        """Exclusive lock over one session's checkpoint.

        Held across a full load -> run workflow -> save sequence (see
        ``agent.service.AgentService.run``/``run_stream``) so two
        concurrent requests on the same session_id can't race: both
        reading the same starting history, then both saving, with
        whichever save lands last silently discarding the other's turn.

        Returns:
            An async context manager; entering it may block until the
            lock is free, and raises if that wait times out.
        """
        ...
