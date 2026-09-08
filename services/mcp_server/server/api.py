"""FastAPI management API + MCP Streamable HTTP mount."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from pathlib import Path

from config import get_config
from core.logger import get_logger
from core.registry import ModuleRegistry
from mcp_singleton import mcp, transport_security

logger = get_logger(__name__)

_start_time = datetime.now(timezone.utc)
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_DASHBOARD_INDEX = _STATIC_DIR / "dashboard" / "index.html"


def create_app(
    registry: ModuleRegistry,
    *,
    start_time: datetime | None = None,
) -> FastAPI:
    """Build the combined FastAPI + Streamable HTTP ASGI application."""
    global _start_time
    if start_time is not None:
        _start_time = start_time

    config = get_config()

    # Build the Streamable HTTP sub-app first so mcp.session_manager exists for lifespan.
    mcp_http_app = mcp.streamable_http_app(
        host=config.host,
        json_response=True,
        transport_security=transport_security(),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Nested mount does not run MCPServer's own lifespan; start session manager here.
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="Metaplanet MCP Server",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.registry = registry

    @app.get("/health")
    async def health_check() -> JSONResponse:
        """Thin ECS/ALB health check."""
        try:
            tools = await mcp.list_tools()
            uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()
            return JSONResponse(
                {
                    "status": "healthy",
                    "service": "mcp-server",
                    "tools_loaded": len(tools),
                    "uptime_seconds": uptime,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            logger.error("Health check failed: %s", exc)
            return JSONResponse(
                {"status": "unhealthy", "error": str(exc)}, status_code=503
            )

    @app.get("/api/health")
    async def api_health(request: Request) -> dict[str, Any]:
        """Full module + shared-service health snapshot."""
        reg: ModuleRegistry = request.app.state.registry
        results = await _refresh_health(reg)
        overall = all(status.healthy for status in results.values()) if results else True
        return {
            "status": "healthy" if overall else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modules": {
                name: {
                    "healthy": status.healthy,
                    "details": status.details,
                }
                for name, status in results.items()
            },
        }

    async def _refresh_health(reg: ModuleRegistry) -> dict[str, Any]:
        """Re-probe health and register tools for modules that just became healthy.

        Without the registration step, dependents that were skipped at bootstrap
        (required module down) stay tool-less even after the dependency recovers.
        """
        from core.context import SharedContext

        context = SharedContext(get_config())
        context.registry = reg
        for name, record in reg.records.items():
            context.set_module(name, record.module)
        results = await reg.run_health_checks(context)
        newly_registered = reg.register_healthy_tools(mcp, context)
        if newly_registered:
            logger.info(
                "Registered %d tool(s) after health recovery: %s",
                len(newly_registered),
                ", ".join(newly_registered),
            )
        return results

    @app.get("/api/dashboard")
    async def api_dashboard(request: Request) -> dict[str, Any]:
        reg: ModuleRegistry = request.app.state.registry
        # Health is refreshed by /api/dashboard/modules (avoid double-probing).
        modules = reg.to_dashboard_modules()
        healthy = sum(1 for m in modules if m.get("healthy") is True)
        unhealthy = sum(1 for m in modules if m.get("healthy") is False)
        connections = [c for m in modules for c in (m.get("connections") or [])]
        connections_ok = sum(1 for c in connections if c.get("status") == "ok")
        connections_bad = sum(
            1 for c in connections if c.get("status") == "unhealthy"
        )
        tool_count = sum(len(m.get("registered_tools") or []) for m in modules)
        uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()
        return {
            "service": "mcp-server",
            "transport": "streamable-http",
            "mcp_path": "/mcp",
            "uptime_seconds": uptime,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modules_total": len(modules),
            "modules_healthy": healthy,
            "modules_unhealthy": unhealthy,
            "connections_total": len(connections),
            "connections_healthy": connections_ok,
            "connections_unhealthy": connections_bad,
            "tools_registered": tool_count,
        }

    @app.get("/api/dashboard/modules")
    async def api_dashboard_modules(request: Request) -> dict[str, Any]:
        reg: ModuleRegistry = request.app.state.registry
        await _refresh_health(reg)
        return {
            "modules": reg.to_dashboard_modules(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/dashboard")
    @app.get("/dashboard/")
    async def dashboard_page() -> Response:
        """Small admin UI for module/tool health."""
        if not _DASHBOARD_INDEX.is_file():
            return JSONResponse(
                {"error": "Dashboard UI not found", "path": str(_DASHBOARD_INDEX)},
                status_code=404,
            )
        return FileResponse(_DASHBOARD_INDEX, media_type="text/html; charset=utf-8")

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Mount Streamable HTTP so /mcp stays on the MCPServer route table.
    # Must be last: catch-all mount would otherwise shadow /dashboard and /api/*.
    app.mount("/", mcp_http_app)
    return app
