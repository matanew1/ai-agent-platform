"""Concrete adapters for external systems (MongoDB, Redis, Qdrant, LLMs).

Nothing in this package is imported by ``modules/*`` directly. Each adapter
here structurally satisfies a ``Protocol`` port defined by the module that
consumes it (e.g. ``QdrantVectorStore`` satisfies ``rag``'s ``VectorStore``
port). Wiring - constructing an adapter and handing it to a module's
service - happens once, at the composition root in ``app/lifespan.py``. See
``.claude/rules/architecture.md``.
"""
