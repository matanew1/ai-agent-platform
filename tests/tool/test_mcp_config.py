"""Unit tests for tool.mcp.config.load_servers.

Reads the real tool/mcp/mcp-servers.yaml file - no mocking, since this is
just parsing a local data file, no network or process involved.
"""

from __future__ import annotations

from tool.mcp.config import load_servers


def test_load_servers_finds_the_fetch_server() -> None:
    servers = load_servers()

    commands = [(s.command, s.args) for s in servers]
    assert (
        "/opt/homebrew/bin/uvx",
        ["--with", "mcp==1.9.4", "mcp-server-fetch"],
    ) in commands
    fetch_server = next(server for server in servers if server.args[-1] == "mcp-server-fetch")
    assert fetch_server.env == {"PATH": "/usr/bin:/bin"}


def test_load_servers_finds_the_duckduckgo_server() -> None:
    """The free search server should be launched from its pinned package."""
    servers = load_servers()

    commands = [(s.command, s.args) for s in servers]
    assert (
        "uvx",
        ["--with", "mcp==1.9.4", "--from", "ddg-mcp==0.1.1", "ddg-mcp"],
    ) in commands
