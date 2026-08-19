"""Unit tests for agent.draft_service.DraftService."""

from __future__ import annotations

from agent.draft_service import DraftService
from agent.service import AgentService

from shared.types import ToolDefinition


class FakeRepository:
    """In-memory repository enforcing the same owner/id lookup semantics."""

    def __init__(self) -> None:
        self.definitions: dict[str, object] = {}

    async def create(self, definition):
        self.definitions[definition.id] = definition
        return definition

    async def get(self, owner_id: str, agent_id: str):
        definition = self.definitions.get(agent_id)
        return definition if definition and definition.owner_id == owner_id else None


class FakeToolRegistry:
    """Two tools, so allowed_tools filtering has something to actually filter."""

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(name="fetch", description="Fetches a URL."),
            ToolDefinition(name="extract_pdf", description="Reads a PDF."),
        ]


class FakeLLM:
    """Records the prompt and the per-agent options it was scoped with."""

    def __init__(self, response: str = "  Rewritten draft.  ") -> None:
        self._response = response
        self.options: list[tuple[str | None, float | None]] = []
        self.prompts: list[str] = []

    def with_options(
        self, *, model: str | None = None, temperature: float | None = None
    ) -> FakeLLM:
        self.options.append((model, temperature))
        return self

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        self.prompts.append(prompt)
        return self._response


def _build(llm: FakeLLM | None = None) -> tuple[DraftService, AgentService, FakeLLM]:
    repository = FakeRepository()
    agent_service = AgentService(repository=repository, tool_registry=FakeToolRegistry())
    llm = llm or FakeLLM()
    return DraftService(agent_service, FakeToolRegistry(), llm), agent_service, llm


async def test_rewrite_returns_none_for_an_agent_not_owned_by_the_caller() -> None:
    draft_service, agent_service, _ = _build()
    agent = await agent_service.create(
        owner_id="owner-1", name="CV Expert", system_prompt="You review CVs.", allowed_tools=[]
    )

    result = await draft_service.rewrite("owner-2", agent.id, "help me")

    assert result is None


async def test_rewrite_returns_the_llm_s_stripped_response() -> None:
    draft_service, agent_service, llm = _build()
    agent = await agent_service.create(
        owner_id="owner-1", name="CV Expert", system_prompt="You review CVs.", allowed_tools=[]
    )

    result = await draft_service.rewrite("owner-1", agent.id, "review my cv")

    assert result == "Rewritten draft."


async def test_rewrite_scopes_the_llm_to_the_agent_s_model_and_temperature() -> None:
    draft_service, agent_service, llm = _build()
    agent = await agent_service.create(
        owner_id="owner-1",
        name="CV Expert",
        system_prompt="You review CVs.",
        allowed_tools=[],
        model="qwen3:8b",
        temperature=0.4,
    )

    await draft_service.rewrite("owner-1", agent.id, "review my cv")

    assert llm.options == [("qwen3:8b", 0.4)]


async def test_rewrite_prompt_includes_the_system_prompt_and_draft() -> None:
    draft_service, agent_service, llm = _build()
    agent = await agent_service.create(
        owner_id="owner-1", name="CV Expert", system_prompt="You review CVs.", allowed_tools=[]
    )

    await draft_service.rewrite("owner-1", agent.id, "review my cv please")

    assert "You review CVs." in llm.prompts[0]
    assert "review my cv please" in llm.prompts[0]


async def test_rewrite_filters_tools_to_the_agent_s_allowlist() -> None:
    draft_service, agent_service, llm = _build()
    agent = await agent_service.create(
        owner_id="owner-1",
        name="CV Expert",
        system_prompt="You review CVs.",
        allowed_tools=["extract_pdf"],
    )

    await draft_service.rewrite("owner-1", agent.id, "review my cv")

    assert "extract_pdf" in llm.prompts[0]
    assert "fetch" not in llm.prompts[0]


async def test_rewrite_with_no_allowlist_includes_every_registered_tool() -> None:
    """An empty allowed_tools means unrestricted, same as the runtime chat path
    (see graph.graph._execute_tools and chat.controller)."""
    draft_service, agent_service, llm = _build()
    agent = await agent_service.create(
        owner_id="owner-1", name="CV Expert", system_prompt="You review CVs.", allowed_tools=[]
    )

    await draft_service.rewrite("owner-1", agent.id, "review my cv")

    assert "fetch" in llm.prompts[0]
    assert "extract_pdf" in llm.prompts[0]
