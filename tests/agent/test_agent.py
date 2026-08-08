"""Unit tests for agent.service.AgentService and its LangGraph workflow.

Every dependency is a hand-written fake satisfying the corresponding
`agent.internal.ports` Protocol - no real LLM, retriever, memory, or tool registry
is touched (that's what the live smoke tests run manually against a real
Ollama server are for - see the project README). `FakeLLMProvider` inspects
the prompt to decide which node is calling it, since the graph sends both
the execute_tools and generate_answer prompts through the same `generate`
method. See `.claude/rules/testing.md`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from agent.internal.graph import AgentError
from agent.service import AgentService

from shared.types import Chunk, SessionCheckpoint, ToolDefinition, ToolResult


class FakeLLMProvider:
    """Fake satisfying agent.internal.ports.LLMProvider.

    Args:
        tool_call: If given, returned (as a single-element JSON array) when
            asked which tools to call. If ``None``, "no tools needed" (``[]``).
        answer: Text returned as the final answer.
    """

    def __init__(
        self, tool_call: dict[str, object] | None = None, answer: str = "the final answer"
    ):
        self._tool_call = tool_call
        self._answer = answer
        self.prompts: list[str] = []

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        self.prompts.append(prompt)
        # A real suspension point, not just an `async def` with no genuine
        # await - lets concurrent callers (see the session_lock regression
        # tests below) actually interleave instead of running one to
        # completion before the other starts.
        await asyncio.sleep(0)
        if "Available tools:" in prompt:
            return json.dumps([self._tool_call]) if self._tool_call else "[]"
        if "Write the final answer" in prompt:
            return self._answer
        raise AssertionError(f"Unexpected prompt reached FakeLLMProvider.generate: {prompt!r}")

    async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        for char in self._answer:
            await asyncio.sleep(0)
            yield char


class FakeRetriever:
    """Fake satisfying agent.internal.ports.Retriever."""

    def __init__(self, chunks: list[Chunk] | None = None):
        self._chunks = chunks if chunks is not None else [Chunk(id="1", text="context", score=0.9)]
        self.queries: list[str] = []

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        self.queries.append(query)
        return self._chunks


class FakeToolRegistry:
    """Fake satisfying agent.internal.ports.ToolRegistry. Always exposes one tool
    ("echo") so execute_tools doesn't short-circuit on an empty tool list.
    """

    def __init__(self):
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_tools(self) -> list[ToolDefinition]:
        return [ToolDefinition(name="echo", description="Echoes its arguments.")]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append((name, arguments))
        return ToolResult(tool_name=name, content={"echoed": arguments})


class FakeMemory:
    """Fake satisfying agent.internal.ports.Memory, backed by a plain dict.

    `session_lock` uses a real `asyncio.Lock` per session_id (in-process,
    fine for a single-event-loop unit test) rather than a no-op, so tests
    can actually verify AgentService holds it across the whole load ->
    run -> save sequence - see the `test_run_serializes_concurrent_requests_
    on_the_same_session` regression test below.
    """

    def __init__(self):
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
    async def session_lock(self, session_id: str):
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            yield


def _make_service(
    llm: FakeLLMProvider | None = None,
    retriever: FakeRetriever | None = None,
    memory: FakeMemory | None = None,
    tool_registry: FakeToolRegistry | None = None,
) -> tuple[AgentService, FakeLLMProvider, FakeRetriever, FakeMemory, FakeToolRegistry]:
    llm = llm or FakeLLMProvider()
    retriever = retriever or FakeRetriever()
    memory = memory or FakeMemory()
    tool_registry = tool_registry or FakeToolRegistry()
    service = AgentService(llm=llm, retriever=retriever, memory=memory, tool_registry=tool_registry)
    return service, llm, retriever, memory, tool_registry


async def test_run_returns_the_generated_answer() -> None:
    service, *_ = _make_service(llm=FakeLLMProvider(answer="42"))

    result = await service.run(session_id="s1", message="what is the answer?")

    assert result.answer == "42"


async def test_run_reports_execution_time() -> None:
    service, *_ = _make_service()

    result = await service.run(session_id="s1", message="what is the answer?")

    assert result.execution_time_seconds > 0


async def test_run_reports_tools_invoked() -> None:
    llm = FakeLLMProvider(tool_call={"name": "echo", "arguments": {"x": 1}})
    service, *_ = _make_service(llm=llm, tool_registry=FakeToolRegistry())

    # "echo" is the registered tool's name, so the input-mention heuristic
    # lets this reach the LLM - see test_run_calls_the_tool_the_llm_requests.
    result = await service.run(session_id="s1", message="echo x=1")

    assert result.tools_invoked == ["echo"]


async def test_run_reports_no_tools_invoked_when_none_were_called() -> None:
    service, *_ = _make_service()  # default LLM requests no tools

    result = await service.run(session_id="s1", message="just answer directly")

    assert result.tools_invoked == []


async def test_run_reports_chunks_retrieved() -> None:
    retriever = FakeRetriever(
        chunks=[Chunk(id="1", text="a", score=0.9), Chunk(id="2", text="b", score=0.8)]
    )
    service, *_ = _make_service(retriever=retriever)

    result = await service.run(session_id="s1", message="what does this platform do?")

    assert result.chunks_retrieved == 2


async def test_run_reports_zero_chunks_when_retrieval_is_skipped() -> None:
    retriever = FakeRetriever()
    service, *_ = _make_service(retriever=retriever)

    result = await service.run(session_id="s1", message="thanks!")  # smalltalk - skips retrieval

    assert result.chunks_retrieved == 0
    assert retriever.queries == []


async def test_run_uses_retriever_for_context() -> None:
    service, _, retriever, _, _ = _make_service()

    await service.run(session_id="s1", message="tell me about the platform")

    assert retriever.queries == ["tell me about the platform"]


async def test_run_calls_the_tool_the_llm_requests() -> None:
    tool_registry = FakeToolRegistry()
    llm = FakeLLMProvider(tool_call={"name": "echo", "arguments": {"x": 1}})
    service, *_ = _make_service(llm=llm, tool_registry=tool_registry)

    # "echo" is the registered tool's name, so the input-mention heuristic
    # (agent.internal.graph._mentions_a_tool) lets this reach the LLM.
    await service.run(session_id="s1", message="echo x=1")

    assert tool_registry.calls == [("echo", {"x": 1})]


async def test_run_calls_no_tools_when_the_llm_requests_none() -> None:
    tool_registry = FakeToolRegistry()
    service, *_ = _make_service(tool_registry=tool_registry)  # default LLM requests no tools

    await service.run(session_id="s1", message="just answer directly")

    assert tool_registry.calls == []


async def test_execute_tools_skips_the_llm_call_when_no_tool_is_mentioned() -> None:
    """The input-mention heuristic should skip the tool-decision LLM call
    entirely (not just decline to call a tool) when no registered tool's
    name is referenced - the whole point is saving that round-trip.
    """
    llm = FakeLLMProvider()
    service, *_ = _make_service(llm=llm)

    await service.run(session_id="s1", message="just answer directly")

    assert not any("Available tools:" in prompt for prompt in llm.prompts)


async def test_retrieve_context_skips_retrieval_for_smalltalk() -> None:
    """The smalltalk heuristic should skip the retriever call entirely (not
    just retrieve and ignore it) on a pure greeting/acknowledgement, same
    saved-round-trip intent as the tool-mention heuristic above.
    """
    retriever = FakeRetriever()
    service, *_ = _make_service(retriever=retriever)

    await service.run(session_id="s1", message="thanks!")

    assert retriever.queries == []


async def test_retrieve_context_still_retrieves_for_a_real_question() -> None:
    retriever = FakeRetriever()
    service, *_ = _make_service(retriever=retriever)

    await service.run(session_id="s1", message="what does this platform do?")

    assert retriever.queries == ["what does this platform do?"]


async def test_run_saves_the_turn_to_memory() -> None:
    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, llm=FakeLLMProvider(answer="the answer"))

    await service.run(session_id="s1", message="the question")

    assert len(memory.saved) == 1
    history = memory.saved[0].history
    assert [(turn.role, turn.content) for turn in history] == [
        ("user", "the question"),
        ("assistant", "the answer"),
    ]


async def test_run_appends_to_existing_history() -> None:
    memory = FakeMemory()
    memory.seed(
        SessionCheckpoint(
            session_id="s1",
            history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        )
    )
    service, *_ = _make_service(memory=memory)

    await service.run(session_id="s1", message="follow-up question")

    assert len(memory.saved[0].history) == 4


async def test_run_serializes_concurrent_requests_on_the_same_session() -> None:
    """Regression test for the lost-update race AgentService.run's
    session_lock guards against: two concurrent .run() calls on the same
    session_id must not both read the same starting history and then both
    save, with the second silently overwriting the first's turn. Relies on
    FakeMemory.session_lock's real asyncio.Lock and FakeLLMProvider's
    genuine await point to actually exercise the interleaving - before the
    session_lock fix, this fails with only 2 messages (one turn) in the
    final checkpoint instead of 4 (both turns).
    """
    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, llm=FakeLLMProvider(answer="ok"))

    await asyncio.gather(
        service.run(session_id="s1", message="first"),
        service.run(session_id="s1", message="second"),
    )

    assert len(memory.saved) == 2
    assert len(memory.saved[-1].history) == 4


async def test_run_stream_serializes_concurrent_requests_on_the_same_session() -> None:
    """Same regression as above, for run_stream - the lock must span every
    yield, not just the setup before the first one.
    """
    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, llm=FakeLLMProvider(answer="ok"))

    async def consume(message: str) -> None:
        _, stream = await service.run_stream(session_id="s1", message=message)
        async for _ in stream:
            pass

    await asyncio.gather(consume("first"), consume("second"))

    assert len(memory.saved) == 2
    assert len(memory.saved[-1].history) == 4


async def test_run_raises_agent_error_when_llm_returns_no_answer() -> None:
    service, *_ = _make_service(llm=FakeLLMProvider(answer=""))

    with pytest.raises(AgentError):
        await service.run(session_id="s1", message="hello")


async def test_run_stream_releases_the_session_lock_if_prep_fails() -> None:
    """Regression test for the AsyncExitStack cleanup path: run_stream's
    lock is entered manually (not `async with`) because it has to span
    past the method's own return - a failure during prep must still
    release it, or a later call on the same session_id deadlocks forever.
    """

    class FailingRetriever:
        async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
            raise RuntimeError("retrieval broke")

    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, retriever=FailingRetriever())

    # _retrieve_context wraps the retriever's failure as AgentError - see
    # agent.internal.graph.
    with pytest.raises(AgentError):
        await service.run_stream(session_id="s1", message="a real question")

    # If the lock leaked, this hangs forever instead of completing.
    metadata, stream = await asyncio.wait_for(
        service.run_stream(session_id="s1", message="thanks!"), timeout=1
    )
    async for _ in stream:
        pass
    assert metadata.tools_invoked == []


async def test_run_stream_yields_the_answer_in_chunks_and_saves_it() -> None:
    memory = FakeMemory()
    service, *_ = _make_service(memory=memory, llm=FakeLLMProvider(answer="hello world"))

    _, stream = await service.run_stream(session_id="s1", message="hi")
    chunks = [chunk async for chunk in stream]

    assert "".join(chunks) == "hello world"
    assert len(chunks) > 1  # actually streamed, not one big chunk
    assert len(memory.saved) == 1
    assert [(turn.role, turn.content) for turn in memory.saved[0].history] == [
        ("user", "hi"),
        ("assistant", "hello world"),
    ]


async def test_run_stream_returns_metadata_before_the_stream_starts() -> None:
    llm = FakeLLMProvider(tool_call={"name": "echo", "arguments": {"x": 1}}, answer="ok")
    retriever = FakeRetriever(chunks=[Chunk(id="1", text="a", score=0.9)])
    service, *_ = _make_service(llm=llm, retriever=retriever, tool_registry=FakeToolRegistry())

    # "echo" mentioned so the tool-call heuristic reaches the LLM, same as
    # test_run_calls_the_tool_the_llm_requests.
    metadata, stream = await service.run_stream(session_id="s1", message="echo x=1")

    assert metadata.tools_invoked == ["echo"]
    assert metadata.chunks_retrieved == 1
    assert metadata.prep_time_seconds > 0
    async for _ in stream:  # drain so the lock releases before the test ends
        pass


async def test_run_stream_raises_agent_error_when_the_stream_fails() -> None:
    class BrokenStreamLLMProvider(FakeLLMProvider):
        async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
            self.prompts.append(prompt)
            raise RuntimeError("stream broke")
            yield  # pragma: no cover - unreachable, just marks this an async generator

    service, *_ = _make_service(llm=BrokenStreamLLMProvider())

    with pytest.raises(AgentError):
        _, stream = await service.run_stream(session_id="s1", message="hello")
        async for _ in stream:
            pass
