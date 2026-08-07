"""Agent internals: state, ports, prompts, exceptions, and the LangGraph
workflow itself.

Not part of this module's public surface - nothing outside `agent` imports
from here. `agent.service.AgentService` is the module's one supported
entry point; `agent.api.router` is its HTTP surface. See
`.claude/rules/architecture.md` on the root-vs-`internal/` convention.
"""
