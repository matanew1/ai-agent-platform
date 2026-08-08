"""Cross-cutting data shapes and the common exception base.

These types are the only things a module is allowed to share with another
module directly (see ``.claude/rules/architecture.md``). Anything more than
this belongs inside the module that owns the concept.
"""

from __future__ import annotations

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


class ChatMessage(BaseModel):
    """One turn of a conversation.

    Used both for conversation history (``SessionCheckpoint.history``,
    ``agent.internal.graph.AgentState.history``) and for API request/response bodies
    that need to carry a turn - a generic enough shape for either.

    Attributes:
        role: Who said it.
        content: The message text.
    """

    role: Literal["user", "assistant"]
    content: str


class SessionCheckpoint(BaseModel):
    """Persisted agent session state, keyed by session id in Redis.

    Stored as ``agent_session:{session_id}`` (see
    ``infrastructure/redis.py``) and read/written through the ``Memory``
    port that ``agent`` depends on. Loaded at the start of a turn to seed
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


class AgentDefinition(BaseModel):
    """A versioned, user-owned configuration for one conversational agent.

    Runtime services are derived from this persistent definition and cached
    separately; editing a definition increments ``version`` so a future
    request cannot reuse a runtime compiled for stale configuration.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    name: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(min_length=1, max_length=8_000)
    allowed_tools: list[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
