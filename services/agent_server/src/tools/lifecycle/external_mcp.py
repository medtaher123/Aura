"""Reconcile MCP server definitions.

* **Metaplanet MCP** is first-party: ensured from ``MCP_SERVER_URL`` / app
  config (not the YAML file).
* **External MCP servers** come from ``config/external_mcp_servers.yaml``.

Runtime ``enabled`` is owned by the database / admin toggle and is preserved
across reconciles for existing rows.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import AgentServerConfig, get_config
from src.core.logger import get_logger
from src.db.models.mcp_server import McpServer
from src.db.repositories.tool_platform import McpServerRepository
from src.tools.providers.metaplanet import (
    METAPLANET_MCP_DISPLAY_NAME,
    METAPLANET_MCP_SLUG,
    is_metaplanet_server,
)

logger = get_logger("tool_platform.external_mcp")

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")

_DEFAULT_CONFIG_RELPATH = "config/external_mcp_servers.yaml"


@dataclass
class ReconcileResult:
    """Outcome of reconciling MCP server definitions."""

    created: int = 0
    updated: int = 0


def default_external_mcp_config_path(
    config: AgentServerConfig | None = None,
) -> Path:
    config = config or get_config()
    configured = (config.external_mcp_config_file or "").strip()
    if configured:
        path = Path(configured)
        if path.is_absolute():
            return path
        service_root = Path(__file__).resolve().parents[3]
        return (service_root / path).resolve()
    return Path(__file__).resolve().parents[3] / _DEFAULT_CONFIG_RELPATH


def expand_env(value: Any) -> Any:
    """Replace ``${VAR}`` placeholders from the process environment."""
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            return os.getenv(match.group(1), "")

        return _ENV_PATTERN.sub(repl, value).strip()
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    return value


def resolve_node_runner_base_url(port: int) -> str:
    """Build ``{NODE_MCP_URL}:{port}`` for a node-runner MCP entry."""
    raw = (os.getenv("NODE_MCP_URL") or "http://localhost").strip()
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "localhost"
    return f"{scheme}://{host}:{int(port)}"


def load_external_mcp_config(path: Path | None = None) -> dict[str, Any]:
    config = get_config()
    config_path = path or default_external_mcp_config_path(config)
    if not config_path.is_file():
        raise FileNotFoundError(
            f"External MCP config file not found: {config_path}"
        )
    # YAML ``${VAR}`` expansion reads the process env; load the service .env
    # so keys that are not pydantic Settings fields (e.g. PAPPERS_API_KEY) exist.
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"External MCP config file must be a mapping: {config_path}"
        )
    return expand_env(raw)


class ExternalMcpReconciler:
    """Ensure Metaplanet MCP from config; reconcile external servers from YAML."""

    def __init__(self, *, config_path: Path | None = None) -> None:
        self._config_path = config_path

    async def reconcile(self, db: AsyncSession) -> ReconcileResult:
        """Ensure primary Metaplanet row, then upsert external servers from YAML."""
        primary = await self.ensure_metaplanet(db)
        external = await self.reconcile_external_from_yaml(db)
        return ReconcileResult(
            created=primary.created + external.created,
            updated=primary.updated + external.updated,
        )

    async def ensure_metaplanet(self, db: AsyncSession) -> ReconcileResult:
        """Upsert the first-party Metaplanet MCP from application config."""
        config = get_config()
        servers_repo = McpServerRepository(db)
        existing = await servers_repo.get_by_slug(METAPLANET_MCP_SLUG)
        base_url = config.mcp_server_url.rstrip("/")

        if existing is None:
            await servers_repo.add(
                McpServer(
                    id=uuid.uuid4(),
                    slug=METAPLANET_MCP_SLUG,
                    display_name=METAPLANET_MCP_DISPLAY_NAME,
                    base_url=base_url,
                    transport="streamable_http",
                    auth_headers={},
                    enabled=True,
                    is_primary=True,
                )
            )
            logger.info(
                "Ensured Metaplanet MCP from config (base_url=%s)",
                base_url,
            )
            return ReconcileResult(created=1)

        changed = False
        if existing.base_url != base_url:
            existing.base_url = base_url
            changed = True
        if existing.display_name != METAPLANET_MCP_DISPLAY_NAME:
            existing.display_name = METAPLANET_MCP_DISPLAY_NAME
            changed = True
        if existing.transport != "streamable_http":
            existing.transport = "streamable_http"
            changed = True
        if not existing.is_primary:
            existing.is_primary = True
            changed = True
        # ``enabled`` is runtime state — do not overwrite.
        if changed:
            await servers_repo.commit()
            logger.info(
                "Updated Metaplanet MCP from config (base_url=%s)",
                base_url,
            )
            return ReconcileResult(updated=1)
        return ReconcileResult()

    async def reconcile_external_from_yaml(self, db: AsyncSession) -> ReconcileResult:
        """Upsert non-Metaplanet MCP servers from YAML."""
        document = load_external_mcp_config(self._config_path)
        result = await self._reconcile_external_mcp_servers(db, document)
        if result.created or result.updated:
            logger.info(
                "Reconciled external MCP servers from %s (created=%d, updated=%d)",
                self._config_path or default_external_mcp_config_path(),
                result.created,
                result.updated,
            )
        return result

    async def _reconcile_external_mcp_servers(
        self,
        db: AsyncSession,
        document: dict[str, Any],
    ) -> ReconcileResult:
        servers_repo = McpServerRepository(db)
        created = 0
        updated = 0

        for entry in document.get("mcp_servers") or []:
            if not isinstance(entry, dict):
                continue
            slug = str(entry.get("slug") or "").strip()
            if not slug:
                continue

            is_primary = bool(entry.get("is_primary", False))
            if is_metaplanet_server(slug=slug, is_primary=is_primary):
                logger.warning(
                    "Ignoring YAML entry for Metaplanet MCP (slug=%s); "
                    "it is managed from MCP_SERVER_URL / app config",
                    slug,
                )
                continue

            base_url = str(entry.get("base_url") or "").rstrip("/")
            transport = str(entry.get("transport") or "streamable_http").strip()
            runner = str(entry.get("runner") or "").strip().lower()
            command = str(entry.get("command") or "").strip()
            args = entry.get("args") or []
            if not isinstance(args, list):
                args = []
            env = entry.get("env") or {}
            if not isinstance(env, dict):
                env = {}
            stdio_config: dict[str, Any] = {}

            if runner == "node":
                port = entry.get("port")
                try:
                    port_int = int(port)
                except (TypeError, ValueError):
                    logger.warning(
                        "Skipping node-runner MCP server %s: valid port is required",
                        slug,
                    )
                    continue
                base_url = resolve_node_runner_base_url(port_int)
                transport = transport or "streamable_http"
            elif transport == "stdio":
                if not command:
                    logger.warning(
                        "Skipping external MCP server %s: stdio requires command",
                        slug,
                    )
                    continue
                stdio_config = {
                    "command": command,
                    "args": [str(a) for a in args],
                }
                if env:
                    stdio_config["env"] = {str(k): str(v) for k, v in env.items()}
                if not base_url:
                    base_url = f"stdio://{slug}"
            elif not base_url:
                logger.warning(
                    "Skipping external MCP server %s: base_url is required",
                    slug,
                )
                continue

            display_name = str(entry.get("display_name") or slug)
            auth_headers = dict(entry.get("auth_headers") or {})
            config_enabled = bool(entry.get("enabled", True))
            if entry.get("append_mcp_path") is False:
                stdio_config["append_mcp_path"] = False

            existing = await servers_repo.get_by_slug(slug)
            if existing is None:
                await servers_repo.add(
                    McpServer(
                        id=uuid.uuid4(),
                        slug=slug,
                        display_name=display_name,
                        base_url=base_url,
                        transport=transport,
                        auth_headers=auth_headers,
                        stdio_config=stdio_config,
                        enabled=config_enabled,
                        is_primary=False,
                    )
                )
                created += 1
                continue

            if existing.is_primary:
                logger.warning(
                    "Skipping YAML update for primary MCP slug=%s",
                    slug,
                )
                continue

            changed = False
            if existing.display_name != display_name:
                existing.display_name = display_name
                changed = True
            if existing.base_url != base_url:
                existing.base_url = base_url
                changed = True
            if existing.transport != transport:
                existing.transport = transport
                changed = True
            if dict(existing.auth_headers or {}) != auth_headers:
                existing.auth_headers = auth_headers
                changed = True
            if dict(existing.stdio_config or {}) != stdio_config:
                existing.stdio_config = stdio_config
                changed = True
            # ``enabled`` is runtime state — do not overwrite from YAML.
            if changed:
                await servers_repo.commit()
                updated += 1

        return ReconcileResult(created=created, updated=updated)
