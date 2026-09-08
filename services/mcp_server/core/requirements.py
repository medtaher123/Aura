"""Declarative module requirements with self-contained health probes.

Kinds
-----
module     Peer MCP module must be loaded and healthy.
config     Configuration value must be present (checked cheaply; no I/O).
connection Live external resource (DB, HTTP API, …). Always probed on refresh.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.base import ProbeResult

if TYPE_CHECKING:
    from core.context import SharedContext

ProbeFn = Callable[["SharedContext"], bool | Awaitable[bool]]


class RequirementKind(str, Enum):
    MODULE = "module"
    CONFIG = "config"
    CONNECTION = "connection"


class Requirement(ABC):
    """Something a module needs in order to operate."""

    name: str
    kind: RequirementKind
    required: bool = True
    label: str = ""

    @abstractmethod
    async def check(self, context: SharedContext) -> ProbeResult:
        """Run this requirement's health probe."""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label or self.name,
            "kind": self.kind.value,
            "required": self.required,
        }


@dataclass
class ModuleRequirement(Requirement):
    """Depends on another discovered MCP module being healthy."""

    name: str
    required: bool = True
    label: str = ""
    kind: RequirementKind = field(default=RequirementKind.MODULE, init=False)

    async def check(self, context: SharedContext) -> ProbeResult:
        registry = context.registry
        if registry is None:
            return ProbeResult(
                healthy=False,
                status="unavailable",
                message="Module registry not attached to context",
            )
        record = registry.records.get(self.name)
        if record is None:
            return ProbeResult(
                healthy=False,
                status="missing",
                message=f"Module '{self.name}' is not loaded",
            )
        if record.health is not None and not record.health.healthy:
            return ProbeResult(
                healthy=False,
                status="unhealthy",
                message=f"Module '{self.name}' is unhealthy",
            )
        from core.registry import ModuleState

        if record.state == ModuleState.UNHEALTHY:
            return ProbeResult(
                healthy=False,
                status="unhealthy",
                message=f"Module '{self.name}' is unhealthy",
            )
        return ProbeResult(
            healthy=True,
            status="ok",
            message=f"Module '{self.name}' is healthy",
        )


@dataclass
class ConfigRequirement(Requirement):
    """Depends on a non-empty configuration value (no live I/O)."""

    name: str
    config_attr: str
    required: bool = True
    label: str = ""
    kind: RequirementKind = field(default=RequirementKind.CONFIG, init=False)

    async def check(self, context: SharedContext) -> ProbeResult:
        value = getattr(context.config, self.config_attr, None)
        if isinstance(value, str):
            configured = bool(value.strip())
        else:
            configured = value is not None and value != ""
        if configured:
            return ProbeResult(
                healthy=True,
                status="configured",
                message=f"{self.label or self.name} is configured",
            )
        return ProbeResult(
            healthy=not self.required,
            status="not_configured",
            message=f"{self.label or self.name} is not configured",
        )


@dataclass
class ConnectionRequirement(Requirement):
    """Depends on a live external connection; probed on every health refresh.

    If ``config_attr`` is set and empty, status is ``not_configured`` (no probe).
    If ``config_attr`` is None, the probe always runs (public endpoints).
    """

    name: str
    probe: ProbeFn
    config_attr: str | None = None
    required: bool = True
    label: str = ""
    kind: RequirementKind = field(default=RequirementKind.CONNECTION, init=False)

    async def check(self, context: SharedContext) -> ProbeResult:
        if self.config_attr is not None:
            value = getattr(context.config, self.config_attr, None)
            if isinstance(value, str):
                configured = bool(value.strip())
            else:
                configured = bool(value)
            if not configured:
                return ProbeResult(
                    healthy=not self.required,
                    status="not_configured",
                    message=f"{self.label or self.name} is not configured",
                )

        try:
            import asyncio

            if inspect.iscoroutinefunction(self.probe):
                outcome = await self.probe(context)
            else:
                outcome = await asyncio.to_thread(self.probe, context)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
            ok = bool(outcome)
        except Exception as exc:
            return ProbeResult(
                healthy=False,
                status="unhealthy",
                message=str(exc),
            )

        if ok:
            return ProbeResult(
                healthy=True,
                status="ok",
                message=f"{self.label or self.name} connection is healthy",
            )
        return ProbeResult(
            healthy=False,
            status="unhealthy",
            message=f"{self.label or self.name} connection failed",
        )


def postgres_probe(config_attr: str, *, timeout: float = 2.0) -> ProbeFn:
    """Build a Postgres SELECT 1 probe for a config URL attr."""

    def _probe(context: SharedContext) -> bool:
        import psycopg

        url = getattr(context.config, config_attr, "")
        if not url:
            return False
        with psycopg.connect(url, connect_timeout=int(timeout)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True

    return _probe


def http_probe(
    config_attr: str,
    *,
    path: str = "",
    timeout: float = 3.0,
    ok_statuses: tuple[int, ...] = (200, 204, 301, 302, 401, 403),
) -> ProbeFn:
    """Build an HTTP reachability probe against a base URL config attr."""

    async def _probe(context: SharedContext) -> bool:
        import httpx

        base = getattr(context.config, config_attr, "") or ""
        if not base:
            return False
        url = base.rstrip("/") + path
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            return response.status_code in ok_statuses

    return _probe


def sqlalchemy_probe(config_attr: str) -> ProbeFn:
    """Probe via SQLAlchemy engine (used by TerraZard)."""

    def _probe(context: SharedContext) -> bool:
        from sqlalchemy import create_engine, text

        url = getattr(context.config, config_attr, "")
        if not url:
            return False
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            engine.dispose()

    return _probe
