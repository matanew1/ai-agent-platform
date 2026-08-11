"""Ports (abstractions) the agent module depends on.

Per ``.claude/rules/architecture.md``, a module depends on interfaces it
owns, not on concrete infrastructure or sibling-module classes. Everything
below is a ``typing.Protocol`` - structural typing, so a class satisfies one
of these just by having the right methods, without importing or inheriting
from it. ``infrastructure/*`` implements ``LLMProvider``/``Memory``;
``rag.service.RAGService`` implements ``Retriever``/``DocumentLibrary``;
``tool.registry.ToolRegistry`` implements ``ToolRegistry``;
``infrastructure.agent_definitions.MongoAgentDefinitionRepository``
implements ``AgentDefinitionRepository``. None of those concrete classes are
ever imported here or by anything else in this module.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from shared.types import (
    AgentDefinition,
    Chunk,
    IndexedDocument,
    ModelCatalogSnapshot,
    SessionCheckpoint,
    ToolDefinition,
    ToolResult,
)

# --- LLM ----------------------------------------------------------------------


class LLMProvider(Protocol):
    """A language model capable of generating text from a prompt."""

    def with_options(
        self, *, model: str | None = None, temperature: float | None = None
    ) -> LLMProvider:
        """Return a provider view with per-agent generation options.

        Implementations may share their underlying HTTP clients; this must
        not open a new connection for every agent runtime.
        """
        ...

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate a completion. ``max_tokens`` caps decision-only calls
        (a routing choice, a JSON tool-call array); ``None`` leaves it
        uncapped, for the user-facing answer."""
        ...

    def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        """Generate a completion, yielding it token-by-token. Only
        ``AgentService.run_stream`` uses this - every other caller wants
        the full string from ``generate``."""
        ...


class ModelCatalog(Protocol):
    """Provider-aware discovery and defaults for agent model configuration."""

    provider_name: str
    default_model: str
    default_temperature: float

    async def available_models(self) -> ModelCatalogSnapshot:
        """Return selectable chat models and whether discovery was authoritative."""
        ...


# --- Retrieval + ingestion ------------------------------------------------------


class Retriever(Protocol):
    """RAG retrieval, as consumed by the workflow and by per-agent scoping
    alike - ``metadata_filter`` is what lets ``AgentRuntimeFactory``'s
    ``AgentScopedRetriever`` wrap this same shape to restrict results to one
    owner's agent, with no special-casing at the call site."""

    async def search(
        self, query: str, top_k: int = 5, metadata_filter: dict[str, str] | None = None
    ) -> list[Chunk]:
        """Find chunks relevant to a query, most relevant first."""
        ...


class DocumentLibrary(Protocol):
    """Owner-scoped document ingestion and source-level management.

    Search remains a separate ``Retriever`` concern. This port only covers
    the public document-library routes: ingesting content, listing indexed
    sources, and deleting one exact source.
    """

    async def ingest_document(
        self,
        text: str,
        source_id: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        metadata: dict[str, str] | None = None,
    ) -> int:
        """Chunk, embed, and index a document. Returns the chunk count."""
        ...

    async def list_documents(self, metadata_filter: dict[str, str]) -> list[IndexedDocument]:
        """List indexed sources whose chunks match every metadata value."""
        ...

    async def delete_document(self, metadata_filter: dict[str, str]) -> bool:
        """Delete every chunk matching the metadata values.

        Returns ``False`` when no matching source existed.
        """
        ...


# --- Tools ----------------------------------------------------------------------


class ToolRegistry(Protocol):
    """Tool discovery and execution. The agent never knows a tool's
    implementation - it only calls by name and gets a typed result back.
    See ``.claude/rules/tool-conventions.md``."""

    def get_tools(self) -> list[ToolDefinition]:
        """List tools currently available."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        """Execute a tool by name. Never raises for an unknown name or a
        failing handler - both come back as ``ToolResult(is_error=True)``."""
        ...


# --- Session memory --------------------------------------------------------------


class Memory(Protocol):
    """Session checkpoint persistence."""

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        """Fetch the stored checkpoint for a session, if any."""
        ...

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        """Persist a session checkpoint."""
        ...

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        """List checkpoints whose session ids begin with ``session_prefix``."""
        ...

    async def delete_checkpoint(self, session_id: str) -> bool:
        """Delete one durable checkpoint and any hot cached copy."""
        ...

    def session_lock(self, session_id: str) -> AbstractAsyncContextManager[None]:
        """Exclusive lock over one session, held across a full load -> run
        -> save sequence so two concurrent requests on the same
        ``session_id`` can't silently drop one turn's save."""
        ...


# --- Agent-definition persistence ------------------------------------------------


class AgentDefinitionRepository(Protocol):
    """Persistence for caller-scoped, versioned agent definitions."""

    async def create(self, definition: AgentDefinition) -> AgentDefinition:
        """Persist a new agent definition."""
        ...

    async def get(self, owner_id: str, agent_id: str) -> AgentDefinition | None:
        """Fetch one definition only when it belongs to ``owner_id``."""
        ...

    async def list(self, owner_id: str) -> list[AgentDefinition]:
        """List definitions belonging to one owner scope."""
        ...

    async def save(self, definition: AgentDefinition) -> bool:
        """Persist an updated definition, matched by owner and id."""
        ...

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        """Delete one definition belonging to the owner scope."""
        ...
