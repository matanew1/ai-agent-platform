"""FastAPI application package - the composition root.

``app`` is the outermost layer in the dependency chain
(``app -> agent -> rag/mcp/llm -> infrastructure``): it is the only place
that constructs concrete ``infrastructure`` adapters and wires them into
module services. Nothing under ``modules/*`` or ``infrastructure/*`` imports
from ``app``.
"""
