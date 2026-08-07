"""Unit tests for tool.mcp.config.load_servers.

Reads the real tool/mcp/mcp-servers.yaml file - no mocking, since this is
just parsing a local data file, no network or process involved.
"""

from __future__ import annotations

from tool.mcp.config import load_servers


def test_load_servers_finds_the_fetch_server() -> None:
    servers = load_servers()

    commands = [(s.command, s.args) for s in servers]
    assert ("uvx", ["--with", "mcp==1.9.4", "mcp-server-fetch"]) in commands
