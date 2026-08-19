"""Unit tests for tool.tools.mcp.config.load_servers.

Reads the real tool/adapters/mcp/mcp-servers.yaml file - no mocking, since this is
just parsing a local data file, no network or process involved.
"""

from __future__ import annotations

import pytest
from tool.tools.mcp.config import McpConfigError, _resolve_env, load_servers


def test_load_servers_finds_the_fetch_server() -> None:
    servers = load_servers()

    names_and_commands = [(name, params.command, params.args) for name, params in servers]
    assert (
        "fetch",
        "/opt/homebrew/bin/uvx",
        ["--with", "mcp==1.9.4", "mcp-server-fetch"],
    ) in names_and_commands
    _, fetch_params = next(pair for pair in servers if pair[1].args[-1] == "mcp-server-fetch")
    assert fetch_params.env == {"PATH": "/usr/bin:/bin"}


def test_load_servers_finds_the_tavily_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """The freemium search server should be launched with its API key resolved from the env."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    servers = load_servers()

    names_and_commands = [(name, params.command, params.args) for name, params in servers]
    assert ("tavily", "npx", ["-y", "tavily-mcp@latest"]) in names_and_commands
    _, tavily_params = next(pair for pair in servers if "tavily-mcp@latest" in pair[1].args)
    assert tavily_params.env == {"TAVILY_API_KEY": "test-key"}


def test_load_servers_skips_a_server_whose_env_var_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing secret drops just that server, not every server in the file."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    servers = load_servers()

    names = [name for name, _ in servers]
    assert "tavily" not in names
    assert "fetch" in names


def test_resolve_env_raises_when_a_referenced_env_var_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(McpConfigError, match="TAVILY_API_KEY"):
        _resolve_env({"TAVILY_API_KEY": "${TAVILY_API_KEY}"}, "tavily")


def test_load_servers_resolves_a_placeholder_in_args_for_the_filesystem_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ${VAR_NAME} placeholder is resolved in `args`, not just `env` - the scoped
    directory is machine-specific the same way a secret is, so it must never be a
    literal path baked into the committed file."""
    monkeypatch.setenv("AGENT_FILES_DIR", "/tmp/agent-files-under-test")

    servers = load_servers()

    names_and_args = [(name, params.args) for name, params in servers]
    assert (
        "filesystem",
        ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/agent-files-under-test"],
    ) in (names_and_args)


def test_load_servers_skips_the_filesystem_server_when_its_directory_env_var_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_FILES_DIR", raising=False)

    servers = load_servers()

    names = [name for name, _ in servers]
    assert "filesystem" not in names
    assert "fetch" in names
