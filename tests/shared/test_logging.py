"""Tests for shared logging presentation and configuration helpers."""

from __future__ import annotations

import logging

import pytest

from shared.logging import ColoredFormatter, _resolve_color_mode, _resolve_level


def _record(level: int, message: str = "database unavailable") -> logging.LogRecord:
    """Build a representative application log record."""
    return logging.LogRecord(
        name="infrastructure.database",
        level=level,
        pathname="/project/infrastructure/database.py",
        lineno=48,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_debug_format_includes_source_location() -> None:
    """Debug logging should identify the exact emitting source line."""
    formatter = ColoredFormatter(use_color=False, debug=True)

    rendered = formatter.format(_record(logging.DEBUG))

    assert "DEBUG" in rendered
    assert " │ [ infrastructure.… ] │ " in rendered
    assert " │ [ database.py:48 ] │ " in rendered
    assert "database.py:48" in rendered
    assert "database unavailable" in rendered


def test_colored_formatter_does_not_mutate_shared_record() -> None:
    """ANSI decoration for one handler must not leak into other handlers."""
    record = _record(logging.ERROR)
    formatter = ColoredFormatter(use_color=True, debug=True)

    rendered = formatter.format(record)

    assert "\033[31mERROR \033[0m" in rendered
    assert "[ \033[31minfrastructure.…\033[0m ]" in rendered
    assert "[ \033[35mdatabase.py\033[0m:48 ]" in rendered
    assert record.levelname == "ERROR"
    assert record.name == "infrastructure.database"
    assert record.filename == "database.py"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("debug", logging.DEBUG), ("WARNING", logging.WARNING)],
)
def test_resolve_level_accepts_case_insensitive_names(value: str, expected: int) -> None:
    """Configured severity names are accepted regardless of casing."""
    assert _resolve_level(value) == expected


def test_invalid_color_mode_explains_valid_options() -> None:
    """Misconfigured color output should fail with an actionable message."""
    with pytest.raises(ValueError, match="auto.*always.*never"):
        _resolve_color_mode("rainbow")
