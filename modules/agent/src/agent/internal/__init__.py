"""Agent internals: state, ports, prompts, exceptions, and the LangGraph
workflow itself.

Not part of this module's public surface - nothing outside `agent` imports
from here. `agent.service.AgentService` is the module's one supported
entry point. The public customizable-agent HTTP surface belongs to the
separate ``agents`` module. See
`.claude/rules/architecture.md` on the root-vs-`internal/` convention.
"""
