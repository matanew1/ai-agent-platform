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
import os
from pathlib import Path

import yaml
from mcp import StdioServerParameters

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "mcp-servers.yaml"


class McpConfigError(Exception):
    """Raised when ``mcp-servers.yaml`` references configuration this process can't satisfy."""


def _resolve_placeholder(value: str, server_name: str) -> str:
    """Resolve one ``${VAR_NAME}`` placeholder against the process env, or pass it through.

    Shared by ``_resolve_env`` (per ``env`` value) and ``load_servers`` (per ``args``
    item), so a server can keep an environment-specific value - a secret, or a
    filesystem path that must never be the same across two machines - out of this
    committed file the same way regardless of which part of its config it lives in.

    Args:
        value: The raw string from YAML - either a literal or a ``${VAR_NAME}`` placeholder.
        server_name: The server's YAML key, used only for the error message.

    Returns:
        ``value`` unchanged if it isn't a placeholder, otherwise the resolved env var.

    Raises:
        McpConfigError: A referenced environment variable isn't set.
    """
    if not (value.startswith("${") and value.endswith("}")):
        return value
    var_name = value[2:-1]
    var_value = os.environ.get(var_name)
    if not var_value:
        raise McpConfigError(
            f"MCP server {server_name!r} requires environment variable "
            f"{var_name!r}, which is not set"
        )
    return var_value


def _resolve_env(env: dict[str, str] | None, server_name: str) -> dict[str, str] | None:
    """Resolve ``${VAR_NAME}`` placeholders in an entry's ``env`` block against the process env.

    A server that needs a secret (an API key) declares it as ``${VAR_NAME}`` in the YAML
    rather than the literal value, so the secret itself lives only in ``.env.dev``/
    ``.env.prod`` (already loaded into the process env before this runs - see
    ``app/main.py``) and never in a file this project commits. Any other value is passed
    through unchanged, e.g. the ``fetch`` entry's literal ``PATH`` override.

    Args:
        env: The entry's raw ``env`` mapping from YAML, or ``None``.
        server_name: The server's YAML key, used only for the error message.

    Returns:
        The same mapping with every ``${VAR_NAME}`` value substituted, or ``None`` if
        ``env`` was ``None``.

    Raises:
        McpConfigError: A referenced environment variable isn't set.
    """
    if env is None:
        return None
    return {key: _resolve_placeholder(value, server_name) for key, value in env.items()}


def load_servers() -> list[tuple[str, StdioServerParameters]]:
    """Parse every server entry in ``tool/adapters/mcp/mcp-servers.yaml``.

    An entry with an unset ``${VAR_NAME}`` placeholder - in ``env`` (a missing API key)
    or in ``args`` (a machine-specific value, e.g. a filesystem path that must never be
    the same literal string across two environments) - is skipped rather than aborting
    the whole file - one server's missing configuration must not take every other,
    correctly-configured server down with it at startup.

    Returns:
        One ``(name, StdioServerParameters)`` pair per top-level key in the file whose
        config could be fully resolved, in file order - the name is the YAML key (e.g.
        ``"fetch"``, ``"tavily"``), passed through to ``ToolService.register_mcp`` so
        each tool it registers can be tagged with the server it came from. Empty if the
        file doesn't exist or declares no servers.

    Raises:
        KeyError: An entry is missing the required ``command`` key.
    """
    if not _CONFIG_PATH.exists():
        return []
    config = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    servers = []
    for name, server_config in config.items():
        try:
            env = _resolve_env(server_config.get("env"), name)
            args = [_resolve_placeholder(arg, name) for arg in server_config.get("args", [])]
        except McpConfigError as error:
            logger.warning("Skipping MCP server %r: %s", name, error)
            continue
        servers.append(
            (
                name,
                StdioServerParameters(
                    command=server_config["command"],
                    args=args,
                    env=env,
                ),
            )
        )
        logger.debug("Loaded MCP server config %r command=%r", name, server_config["command"])
    return servers
