"""Agent module: LangGraph turn execution, versioned agent-definition
management, and the public ``/agents`` HTTP surface, in one package.

Depends only on the abstractions in ``agent.ports`` - never on a concrete
database, cache, vector store, LLM SDK, or a sibling module's concrete
class directly. Concrete implementations are wired in at the composition
root (``app/lifespan.py``). See ``.claude/rules/architecture.md``.

    service.py       - AgentService: runs one chat turn through the graph
    definitions.py    - AgentDefinitionService: CRUD + versioning
    runtime.py         - AgentRuntimeFactory: one compiled AgentService per definition
    graph.py            - AgentState, AgentGraph, AgentError (the LangGraph workflow)
    prompts.py           - prompt templates used by graph.py
    ports.py              - this module's dependency contract
    api/                   - FastAPI router + request/response schemas
"""

from agent.definitions import AgentDefinitionService
from agent.service import AgentService

__all__ = ["AgentDefinitionService", "AgentService"]
