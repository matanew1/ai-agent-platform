"""Cross-cutting primitives shared across modules and infrastructure.

This package has zero dependencies on ``modules/*`` or ``infrastructure/*``.
It exists only to hold data shapes and a base exception type that more than
one module needs to agree on (e.g. both ``rag`` and ``agent`` pass ``Chunk``
objects around). Anything module-specific belongs in that module instead.
"""
