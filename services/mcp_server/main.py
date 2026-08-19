"""MCP server bootstrapper: discover modules, health-check, register tools, serve ASGI."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from config import get_config
from core.context import SharedContext
from core.logger import get_logger
from core.registry import ModuleRegistry
from mcp_singleton import mcp
from server.api import create_app

logger = get_logger(__name__)
config = get_config()


async def bootstrap() -> ModuleRegistry:
    """Discover modules, resolve deps, health-check, and register healthy tools."""
    context = SharedContext(config)
    registry = ModuleRegistry(package_name="modules")
    context.registry = registry

    registry.discover_and_load()
    await registry.initialize_all(context)
    await registry.run_health_checks(context)
    registered = registry.register_healthy_tools(mcp, context)
    logger.info(
        "Bootstrap complete: %d module(s), %d tool(s) registered",
        len(registry.records),
        len(registered),
    )
    return registry


def _maybe_enable_debugpy() -> None:
    if os.getenv("DEBUG", "false").lower() != "true":
        return
    import debugpy

    try:
        debugpy.listen(("0.0.0.0", 5678))
        print("✨ debugpy is listening on port 5678...")
        if os.getenv("DEBUG_WAIT_FOR_CLIENT", "false").lower() == "true":
            print("⏳ Waiting for debugger to attach...")
            debugpy.wait_for_client()
    except RuntimeError as exc:
        if "Address already in use" in str(exc):
            print(
                "⚡ debugpy is already active in the parent process. Skipping dual-binding."
            )
        else:
            raise


_maybe_enable_debugpy()
_registry = asyncio.run(bootstrap())
app = create_app(_registry, start_time=datetime.now(timezone.utc))


def run_server() -> None:
    """Run uvicorn against the combined FastAPI + Streamable HTTP app."""
    import uvicorn

    logger.info("Starting %s v%s", config.name, config.version)
    logger.info("Server running on %s:%s (streamable-http + management API)", config.host, config.port)
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    run_server()
