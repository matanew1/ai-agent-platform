"""Semantic markers for structural protocol implementations.

The decorator deliberately performs no runtime validation and does not create
inheritance. It records the contract a class is intended to satisfy so the
dependency direction remains inverted: infrastructure owns canonical
protocols, while module implementations can document compatibility without
creating inheritance coupling.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

Implementation = TypeVar("Implementation", bound=type)
Contract = type | str


def implements(*contracts: Contract) -> Callable[[Implementation], Implementation]:
    """Mark a class as structurally implementing one or more contracts."""

    def decorate(cls: Implementation) -> Implementation:
        cls.__implemented_contracts__ = contracts
        return cls

    return decorate
