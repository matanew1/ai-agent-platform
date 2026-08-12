"""Vendor SDK imports are confined to designated infrastructure adapters."""

from __future__ import annotations

from pathlib import Path

_VENDOR_IMPORT_ROOTS = {
    "asyncpg",
    "langchain",
    "langchain_ollama",
    "ollama",
    "qdrant_client",
    "redis",
    "jwt",
}
_VENDOR_IMPLEMENTATION_FILES = {
    Path("cache/redis.py"),
    Path("database/postgres.py"),
    Path("llm/ollama.py"),
    Path("vector_database/qdrant.py"),
}


def test_infrastructure_vendor_imports_are_confined_to_adapters() -> None:
    infrastructure = Path(__file__).parents[2] / "infrastructure"
    offenders: list[str] = []
    for path in infrastructure.rglob("*.py"):
        relative_path = path.relative_to(infrastructure)
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            imported = stripped.removeprefix("import ").removeprefix("from ").split(maxsplit=1)[0]
            root = imported.split(".", maxsplit=1)[0]
            is_implementation = relative_path in _VENDOR_IMPLEMENTATION_FILES
            is_vendor_import = root in _VENDOR_IMPORT_ROOTS or root == "sqlalchemy"
            if is_vendor_import and not is_implementation:
                offenders.append(f"{relative_path}: {stripped}")

    assert offenders == []
