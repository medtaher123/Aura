"""MCPServer singleton — no side-effect tool registration."""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from config import get_config


def transport_security() -> TransportSecuritySettings:
    """DNS-rebinding settings for Streamable HTTP.

    MCP SDK only accepts exact Host values or ``host:*`` port wildcards.
    A bare ``*`` does **not** match. Docker Compose uses Host ``mcp-server:8000``,
    which must be allowlisted (or protection disabled for private networks).
    """
    # Private Docker/ECS networks: disable by default (set MCP_DNS_REBINDING_PROTECTION=true to enable).
    enabled = os.getenv("MCP_DNS_REBINDING_PROTECTION", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if not enabled:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    extra_hosts = [
        h.strip()
        for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    ]
    # Always include common local + compose service names (with and without port).
    allowed_hosts = [
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "[::1]",
        "[::1]:*",
        "mcp-server",
        "mcp-server:*",
        *extra_hosts,
    ]
    allowed_origins = [
        "http://localhost",
        "http://localhost:*",
        "http://127.0.0.1",
        "http://127.0.0.1:*",
        "http://[::1]",
        "http://[::1]:*",
        "http://mcp-server",
        "http://mcp-server:*",
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _get_server_instance() -> MCPServer:
    """Create the singleton MCPServer instance (MCP SDK v2)."""
    config = get_config()
    return MCPServer(
        config.name,
        instructions=config.description,
        debug=config.log_level.upper() == "ERROR",
        log_level=config.log_level.upper(),
    )


mcp = _get_server_instance()
