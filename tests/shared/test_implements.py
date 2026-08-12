"""Tests for the semantic structural-contract marker."""

from shared.implements import implements


class _Contract:
    pass


@implements(_Contract, "external.contract")
class _Adapter:
    pass


def test_implements_marks_without_inheritance() -> None:
    assert _Adapter.__implemented_contracts__ == (_Contract, "external.contract")
    assert _Adapter.__bases__ == (object,)
