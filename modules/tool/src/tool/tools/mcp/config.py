"""Load MCP server launch configs from ``tool/adapters/mcp/mcp-servers.yaml``.

One file, one top-level key per server, each with a ``command`` and
``args`` - plain data, no Python. Adding a new server means adding an
entry to that file; nothing else in this module changes, and
``app/lifespan.py`` picks it up automatically since it registers every
server ``load_servers()`` returns (see ``.claude/rules/tool-conventions.md``).

    # tool/adapters/mcp/mcp-servers.yaml
    fetch:
      command: uvx
      args: ["--with", "mcp==1.9.4", "mcp-server-fetch"]
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from mcp import StdioServerParameters

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "mcp-servers.yaml"


def load_servers() -> list[StdioServerParameters]:
    """Parse every server entry in ``tool/adapters/mcp/mcp-servers.yaml``.

    Returns:
        One ``StdioServerParameters`` per top-level key in the file, in
        file order. Empty if the file doesn't exist or declares no servers.

    Raises:
        KeyError: An entry is missing the required ``command`` key.
    """
    if not _CONFIG_PATH.exists():
        return []
    config = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    servers = []
    for name, server_config in config.items():
        servers.append(
            StdioServerParameters(
                command=server_config["command"],
                args=server_config.get("args", []),
                env=server_config.get("env"),
            )
        )
        logger.debug("Loaded MCP server config %r command=%r", name, server_config["command"])
    return servers
