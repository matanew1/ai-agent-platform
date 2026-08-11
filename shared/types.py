"""Cross-cutting data shapes and the common exception base.

These types are the only things a module is allowed to share with another
module directly (see ``.claude/rules/architecture.md``). Anything more than
this belongs inside the module that owns the concept.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class PlatformError(Exception):
    """Base class for every module-level exception hierarchy in this project.

    Each module (``agent``, ``rag``, ``mcp``) defines its own
    exceptions inheriting from this, so callers can catch
    ``PlatformError`` at the API boundary without knowing which module
    raised it. See ``.claude/rules/python-style.md``.
    """


@dataclass(frozen=True, slots=True)
class ModelCatalogSnapshot:
    """One provider model-discovery result.

    ``authoritative`` distinguishes a successful provider inventory from a
    safe fallback returned while discovery is unavailable. Agent-definition
    writes only reject an unknown model against an authoritative snapshot,
    so a temporary Ollama outage cannot make an otherwise valid edit fail.
    """

    models: tuple[str, ...]
    authoritative: bool


class Chunk(BaseModel):
    """A single retrieved unit of context.

    Produced by ``rag`` (via ``VectorStore.search``) and consumed by
    ``agent`` when assembling context for the LLM.

    Attributes:
        id: Stable identifier of the chunk in the vector store.
        text: The chunk's raw text content.
        score: Similarity score for this result, higher is more relevant.
        metadata: Source-specific metadata (e.g. document id, page number).
    """

    id: str
    text: str
    score: float
    metadata: dict[str, str] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    """Description of a callable tool, as exposed to the agent.

    Produced by local tools or external MCP servers
    and consumed by ``agent`` when deciding which tool to call. Mirrors the
    shape an LLM tool-calling API expects.

    Attributes:
        name: Unique, action-oriented tool name (e.g. ``extract_pdf``).
        description: What the tool does and when to use it. This is what
            the LLM uses to decide whether to call the tool - keep it
            complete, per ``.claude/rules/tool-conventions.md``.
        parameters: JSON-schema-shaped description of the tool's arguments.
    """

    name: str
    description: str
    parameters: dict[str, object] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Outcome of a single tool call.

    Attributes:
        tool_name: Name of the tool that was called.
        content: Tool output, already reduced to a plain JSON-serializable
            shape - callers never receive the raw MCP/SDK response object.
        is_error: Whether the tool call failed.
    """

    tool_name: str
    content: object
    is_error: bool = False


class ArtifactReference(BaseModel):
    """Public metadata for a generated file that can be downloaded by a client."""

    filename: str
    download_url: str


class ChatMessage(BaseModel):
    """One turn of a conversation.

    Used both for conversation history (``SessionCheckpoint.history``,
    ``agent.graph.AgentState.history``) and for API request/response bodies
    that need to carry a turn - a generic enough shape for either.

    Attributes:
        role: Who said it.
        content: The message text.
        tools_invoked: Tools used to prepare an assistant response.
        chunks_retrieved: Retrieved context count for an assistant response.
        prep_time_seconds: Retrieval/tool preparation duration, when measured.
        artifacts: Downloadable files generated for this assistant response.
    """

    role: Literal["user", "assistant"]
    content: str
    tools_invoked: list[str] = Field(default_factory=list)
    chunks_retrieved: int = Field(default=0, ge=0)
    prep_time_seconds: float | None = Field(default=None, ge=0)
    artifacts: list[ArtifactReference] = Field(default_factory=list)


class SessionCheckpoint(BaseModel):
    """Persisted agent session state, durably keyed by session id.

    MongoDB owns the durable copy; Redis holds only a short-lived hot cache
    and the distributed lock (see ``infrastructure/sessions.py``). The
    checkpoint is read/written through the ``Memory`` port. Loaded at the start of a turn to seed
    ``AgentState.history`` and saved at the end with that turn appended -
    see ``agent.service.AgentService.run``.

    Attributes:
        session_id: Conversation/session identifier.
        history: Prior turns, oldest first.
        updated_at: Last time this checkpoint was written.
    """

    session_id: str
    history: list[ChatMessage] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IndexedDocument(BaseModel):
    """One successfully indexed source in the shared document library.

    Vector stores persist one point per chunk, while API consumers reason
    about whole source documents. ``RAGService.list_documents`` aggregates
    those points into this source-level shape.
    """

    source_id: str
    chunks_indexed: int = Field(ge=1)


class AgentDefinition(BaseModel):
    """A versioned, user-owned configuration for one conversational agent.

    Runtime services are derived from this persistent definition and cached
    separately; editing a definition increments ``version`` so a future
    request cannot reuse a runtime compiled for stale configuration.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    system_prompt: str = Field(min_length=1, max_length=8_000)
    allowed_tools: list[str] = Field(default_factory=list)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
