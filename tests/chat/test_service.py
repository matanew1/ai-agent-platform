"""Unit tests for ``chat.service`` - ``ChatService`` and ``build_chat_service``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from chat.service import ChatService, _retrieved_sources, build_chat_service
from graph.graph import AgentError, OwnerScopedRetriever

from shared.types import Agent, ChatMessage, Chunk, SessionCheckpoint, ToolDefinition, ToolResult


class FakeLLMProvider:
    """Minimal LLM fake that streams its configured answer one character at a time."""

    def __init__(
        self,
        tool_call: dict[str, object] | None = None,
        answer: str = "the final answer",
        artifact_content: str = "the generated document",
    ) -> None:
        self._tool_call = tool_call
        self._answer = answer
        self._artifact_content = artifact_content
        self.prompts: list[str] = []

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        self.prompts.append(prompt)
        await asyncio.sleep(0)
        if "Create the complete" in prompt:
            return self._artifact_content
        return (
            json.dumps([self._tool_call])
            if "Agent-enabled tools:" in prompt and self._tool_call
            else "[]"
        )

    async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        for character in self._answer:
            await asyncio.sleep(0)
            yield character


class FakeRetriever:
    """Retriever fake that records search queries."""

    def __init__(self, chunks: list[Chunk] | None = None) -> None:
        self._chunks = chunks if chunks is not None else [Chunk(id="1", text="context", score=0.9)]
        self.queries: list[str] = []

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        self.queries.append(query)
        return self._chunks


class FakeToolService:
    """Tool-registry fake with an ``echo`` tool available by default."""

    def __init__(self, extra_tools: list[ToolDefinition] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._tools = [ToolDefinition(name="echo", description="Echoes its arguments.")] + (
            extra_tools or []
        )

    def get_tools(self) -> list[ToolDefinition]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append((name, arguments))
        if name == "generate_pdf":
            return ToolResult(
                tool_name=name,
                content={
                    "filename": "matan-bardugo.pdf",
                    "download_url": "/artifacts/matan-bardugo.pdf",
                    "pages": 1,
                },
            )
        return ToolResult(tool_name=name, content={"echoed": arguments})


class FakeMemory:
    """In-memory checkpoint and per-session lock implementation."""

    def __init__(self) -> None:
        self.saved: list[SessionCheckpoint] = []
        self._store: dict[str, SessionCheckpoint] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        return self._store.get(session_id)

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        self.saved.append(checkpoint)
        self._store[checkpoint.session_id] = checkpoint

    def seed(self, checkpoint: SessionCheckpoint) -> None:
        self._store[checkpoint.session_id] = checkpoint

    @asynccontextmanager
    async def session_lock(self, session_id: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            yield


def _make_service(
    llm: FakeLLMProvider | None = None,
    retriever: FakeRetriever | None = None,
    memory: FakeMemory | None = None,
    tool_registry: FakeToolService | None = None,
) -> tuple[ChatService, FakeLLMProvider, FakeRetriever, FakeMemory, FakeToolService]:
    llm = llm or FakeLLMProvider()
    retriever = retriever or FakeRetriever()
    memory = memory or FakeMemory()
    tool_registry = tool_registry or FakeToolService()
    return (
        ChatService(llm=llm, retriever=retriever, memory=memory, tool_registry=tool_registry),
        llm,
        retriever,
        memory,
        tool_registry,
    )


async def test_run_stream_yields_the_answer_and_saves_the_turn() -> None:
    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, llm=FakeLLMProvider(answer="hello world"))

    _, stream = await service.run_stream(session_id="s1", message="hi")
    chunks = [chunk async for chunk in stream]

    assert "".join(chunks) == "hello world"
    assert len(chunks) > 1
    assert [(turn.role, turn.content) for turn in memory.saved[0].history] == [
        ("user", "hi"),
        ("assistant", "hello world"),
    ]


async def test_run_stream_returns_metadata_after_retrieval_and_tool_execution() -> None:
    llm = FakeLLMProvider(tool_call={"name": "echo", "arguments": {"x": 1}}, answer="ok")
    retriever = FakeRetriever(chunks=[Chunk(id="1", text="a", score=0.9)])
    memory = FakeMemory()
    service, _, _, _, tools = _make_service(llm=llm, retriever=retriever, memory=memory)

    metadata, stream = await service.run_stream(session_id="s1", message="echo x=1")
    async for _ in stream:
        pass

    assert metadata.tools_invoked == ["echo"]
    assert metadata.chunks_retrieved == 1
    assert tools.calls == [("echo", {"x": 1})]
    saved_answer = memory.saved[-1].history[-1]
    assert saved_answer.tools_invoked == ["echo"]
    assert saved_answer.chunks_retrieved == 1
    assert saved_answer.prep_time_seconds == metadata.prep_time_seconds
    tool_prompt = next(prompt for prompt in llm.prompts if "Agent-enabled tools:" in prompt)
    assert "Retrieved context:\n- a" in tool_prompt
    assert "MUST call it" in tool_prompt
    assert "supplied document text" in tool_prompt
    assert "intentionally enabled" in tool_prompt
    assert "Never invent, hallucinate" in tool_prompt


def test_retrieved_sources_show_chat_upload_filename_without_internal_id() -> None:
    sources = _retrieved_sources(
        [
            Chunk(
                id="1",
                text="A concise resume excerpt.",
                score=0.9,
                metadata={
                    "source_id": "chat/27efc292-b616-48ca-93ca-d1104601089b/"
                    "947a3ee5b34ea102-Matan Bardugo CV 2026.pdf"
                },
            )
        ]
    )

    assert sources[0].source_id == "Matan Bardugo CV 2026.pdf"


async def test_generate_pdf_uses_retrieved_context_and_conversation_history() -> None:
    pdf_tool = ToolDefinition(
        name="generate_pdf",
        description="Create a PDF from supplied text.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    tools = FakeToolService(extra_tools=[pdf_tool])
    llm = FakeLLMProvider(
        artifact_content="Matan Bardugo is a backend engineer in Israel.",
        answer="Created: /artifacts/matan-bardugo.pdf",
    )
    retriever = FakeRetriever(
        chunks=[Chunk(id="profile", text="Matan works on AI-powered backend systems.", score=0.9)]
    )
    memory = FakeMemory()
    memory.seed(
        SessionCheckpoint(
            session_id="s1",
            history=[
                {"role": "user", "content": "Tell me about Matan Bardugo."},
                {"role": "assistant", "content": "He is a backend engineer."},
            ],
        )
    )
    service, *_ = _make_service(
        llm=llm,
        retriever=retriever,
        memory=memory,
        tool_registry=tools,
    )

    metadata, stream = await service.run_stream(
        session_id="s1",
        message="Can you genereate a PDF about him?",
        tools=["generate_pdf"],
    )
    answer = "".join([chunk async for chunk in stream])

    assert metadata.tools_invoked == ["generate_pdf"]
    assert [artifact.model_dump() for artifact in metadata.artifacts] == [
        {
            "filename": "matan-bardugo.pdf",
            "download_url": "/artifacts/matan-bardugo.pdf",
        }
    ]
    assert tools.calls == [
        ("generate_pdf", {"text": "Matan Bardugo is a backend engineer in Israel."})
    ]
    artifact_prompt = next(prompt for prompt in llm.prompts if "Create the complete" in prompt)
    assert "Tell me about Matan Bardugo" in artifact_prompt
    assert "Matan works on AI-powered backend systems" in artifact_prompt
    assert answer == "Created: /artifacts/matan-bardugo.pdf"
    assert memory.saved[-1].history[-1].artifacts == metadata.artifacts


async def test_generate_pdf_respects_the_tool_allowlist() -> None:
    pdf_tool = ToolDefinition(name="generate_pdf", description="Create a PDF.")
    tools = FakeToolService(extra_tools=[pdf_tool])
    service, *_ = _make_service(tool_registry=tools)

    with pytest.raises(AgentError, match="disabled for this agent"):
        await service.run_stream(
            session_id="s1",
            message="Generate a PDF about the retrieved profile.",
            tools=["echo"],
        )

    assert tools.calls == []


async def test_run_stream_honors_the_tool_allowlist() -> None:
    tools = FakeToolService(extra_tools=[ToolDefinition(name="shout", description="Shouts.")])
    llm = FakeLLMProvider(tool_call={"name": "shout", "arguments": {"x": 1}})
    service, *_ = _make_service(llm=llm, tool_registry=tools)

    _, stream = await service.run_stream(session_id="s1", message="echo x=1", tools=["echo"])
    async for _ in stream:
        pass

    assert tools.calls == []


async def test_run_stream_skips_retrieval_for_smalltalk() -> None:
    retriever = FakeRetriever()
    service, *_ = _make_service(retriever=retriever)

    _, stream = await service.run_stream(session_id="s1", message="thanks!")
    async for _ in stream:
        pass

    assert retriever.queries == []


async def test_run_stream_serializes_concurrent_requests_on_the_same_session() -> None:
    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, llm=FakeLLMProvider(answer="ok"))

    async def consume(message: str) -> None:
        _, stream = await service.run_stream(session_id="s1", message=message)
        async for _ in stream:
            pass

    await asyncio.gather(consume("first"), consume("second"))

    assert len(memory.saved) == 2
    assert len(memory.saved[-1].history) == 4


async def test_run_stream_releases_its_lock_when_preparation_fails() -> None:
    class FailingRetriever:
        async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
            raise RuntimeError("retrieval broke")

    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, retriever=FailingRetriever())

    with pytest.raises(AgentError):
        await service.run_stream(session_id="s1", message="a real question")

    _, stream = await asyncio.wait_for(service.run_stream(session_id="s1", message="thanks!"), 1)
    async for _ in stream:
        pass


async def test_run_stream_folds_attachments_into_the_answer_prompt_only() -> None:
    """Attached-file text must reach the answer prompt but never the saved
    turn - ephemeral means gone after this turn, not remembered forever.
    """
    memory = FakeMemory()
    llm = FakeLLMProvider(answer="ok")
    service, *_ = _make_service(memory=memory, llm=llm)

    _, stream = await service.run_stream(
        session_id="s1",
        message="summarize this",
        attachments=[("notes.txt", "the quarterly numbers are up 12%")],
    )
    async for _ in stream:
        pass

    answer_prompt = llm.prompts[-1]
    assert "notes.txt" in answer_prompt
    assert "the quarterly numbers are up 12%" in answer_prompt
    saved_message = memory.saved[0].history[0]
    assert saved_message.content == "summarize this"
    assert "quarterly numbers" not in saved_message.content


async def test_run_stream_bounds_durable_history_to_the_context_window() -> None:
    memory = FakeMemory()
    memory.seed(
        SessionCheckpoint(
            session_id="s1",
            history=[ChatMessage(role="user", content=f"message-{index}") for index in range(50)],
        )
    )
    llm = FakeLLMProvider(answer="bounded answer")
    service, *_ = _make_service(memory=memory, llm=llm)

    _, stream = await service.run_stream(session_id="s1", message="latest question")
    async for _ in stream:
        pass

    saved = memory.saved[-1]
    assert len(saved.history) == 40
    assert saved.history[-2].content == "latest question"
    assert saved.history[-1].content == "bounded answer"
    assert "message-0" not in llm.prompts[-1]
    assert "message-49" in llm.prompts[-1]


async def test_run_stream_wraps_a_generation_failure_as_agent_error() -> None:
    class BrokenStreamLLMProvider(FakeLLMProvider):
        async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
            raise RuntimeError("stream broke")
            yield  # pragma: no cover

    service, *_ = _make_service(llm=BrokenStreamLLMProvider())

    with pytest.raises(AgentError, match="stream broke"):
        _, stream = await service.run_stream(session_id="s1", message="hello")
        async for _ in stream:
            pass


class FakeFilterAwareRetriever:
    """Fake satisfying rag.service.RAGService's search shape.

    Records the filter it was called with - used for OwnerScopedRetriever,
    which FakeRetriever above doesn't exercise (it never receives a
    metadata_filter).
    """

    def __init__(self, chunks: list[Chunk] | None = None) -> None:
        self._chunks = chunks if chunks is not None else [Chunk(id="1", text="doc", score=0.9)]
        self.metadata_filters: list[dict[str, str] | None] = []

    async def search(
        self, query: str, top_k: int = 5, metadata_filter: dict[str, str] | None = None
    ) -> list[Chunk]:
        self.metadata_filters.append(metadata_filter)
        return self._chunks[:top_k]


class FakeConfigurableLLM:
    """Records the per-agent options requested by the runtime factory."""

    def __init__(self) -> None:
        self.options: list[tuple[str | None, float | None]] = []

    def with_options(
        self, *, model: str | None = None, temperature: float | None = None
    ) -> FakeConfigurableLLM:
        self.options.append((model, temperature))
        return self


async def test_owner_scoped_retriever_search_scopes_by_owner_id_only() -> None:
    retriever = FakeFilterAwareRetriever()
    scoped = OwnerScopedRetriever(retriever, owner_id="owner-1")

    await scoped.search("query")

    assert retriever.metadata_filters == [{"owner_id": "owner-1"}]


async def test_owner_scoped_retriever_search_returns_the_underlying_retrievers_results() -> None:
    chunks = [Chunk(id="1", text="a", score=0.9), Chunk(id="2", text="b", score=0.8)]
    retriever = FakeFilterAwareRetriever(chunks)
    scoped = OwnerScopedRetriever(retriever, owner_id="owner-1")

    results = await scoped.search("query", top_k=2)

    assert results == chunks


def test_build_chat_service_applies_the_agents_generation_options() -> None:
    llm = FakeConfigurableLLM()
    definition = Agent(
        owner_id="owner-1",
        name="Researcher",
        system_prompt="Research carefully.",
        model="qwen3:14b",
        temperature=0.3,
    )

    runtime = build_chat_service(
        definition,
        llm=llm,
        retriever=FakeFilterAwareRetriever(),
        memory=object(),
        tool_registry=object(),
    )

    assert isinstance(runtime, ChatService)
    assert llm.options == [("qwen3:14b", 0.3)]


def test_build_chat_service_returns_a_fresh_runtime_each_call() -> None:
    llm = FakeConfigurableLLM()
    definition = Agent(
        owner_id="owner-1",
        name="Researcher",
        system_prompt="Research carefully.",
        model="qwen3:14b",
        temperature=0.3,
    )
    dependencies = dict(
        llm=llm, retriever=FakeFilterAwareRetriever(), memory=object(), tool_registry=object()
    )

    first = build_chat_service(definition, **dependencies)
    second = build_chat_service(definition, **dependencies)

    assert first is not second
