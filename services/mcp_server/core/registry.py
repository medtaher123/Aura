"""Dynamic discovery, dependency resolution, and health-gated loading of modules."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.base import BaseModule, HealthStatus
from core.logger import get_logger
from core.requirements import RequirementKind

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext

logger = get_logger(__name__)


class ModuleState(str, Enum):
    DISCOVERED = "discovered"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    TOOLS_REGISTERED = "tools_registered"


@dataclass
class ModuleRecord:
    module: BaseModule
    state: ModuleState = ModuleState.DISCOVERED
    health: HealthStatus | None = None
    registered_tools: list[str] = field(default_factory=list)
    error: str | None = None


class ModuleRegistry:
    """Discover BaseModule subclasses under modules/ and load them in DAG order."""

    def __init__(self, package_name: str = "modules") -> None:
        self.package_name = package_name
        self.records: dict[str, ModuleRecord] = {}
        self.load_order: list[str] = []

    def discover_and_load(self) -> list[BaseModule]:
        """Import modules.<name>.module and instantiate BaseModule subclasses."""
        try:
            package = importlib.import_module(self.package_name)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                f"Module package '{self.package_name}' not found"
            ) from exc

        package_paths = list(getattr(package, "__path__", []))
        discovered: list[BaseModule] = []

        for module_info in pkgutil.iter_modules(package_paths):
            if not module_info.ispkg:
                continue
            submodule_name = f"{self.package_name}.{module_info.name}.module"
            try:
                submodule = importlib.import_module(submodule_name)
            except Exception as exc:
                logger.error("Failed to import %s: %s", submodule_name, exc)
                continue

            for _, obj in inspect.getmembers(submodule, inspect.isclass):
                if not issubclass(obj, BaseModule) or obj is BaseModule:
                    continue
                if inspect.isabstract(obj):
                    continue
                instance: BaseModule = obj()
                if instance.name in self.records:
                    raise RuntimeError(
                        f"Duplicate module name '{instance.name}' from {submodule_name}"
                    )
                self.records[instance.name] = ModuleRecord(module=instance)
                discovered.append(instance)
                logger.info(
                    "Discovered module %s v%s", instance.name, instance.version
                )

        self.load_order = self.resolve_dependency_order()
        return [self.records[name].module for name in self.load_order]

    def resolve_dependency_order(self) -> list[str]:
        """Topologically sort modules by MODULE requirements (Kahn)."""
        names = set(self.records.keys())
        indegree: dict[str, int] = {name: 0 for name in names}
        edges: dict[str, list[str]] = defaultdict(list)

        for name, record in self.records.items():
            for req in record.module.requirements:
                if req.kind is not RequirementKind.MODULE:
                    continue
                if req.name not in names:
                    if req.required:
                        raise RuntimeError(
                            f"Module '{name}' requires missing module '{req.name}'"
                        )
                    continue
                edges[req.name].append(name)
                indegree[name] += 1

        queue: deque[str] = deque(
            sorted(name for name, degree in indegree.items() if degree == 0)
        )
        ordered: list[str] = []

        while queue:
            current = queue.popleft()
            ordered.append(current)
            for dependent in sorted(edges[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)

        if len(ordered) != len(names):
            remaining = sorted(names - set(ordered))
            raise RuntimeError(
                f"Circular module dependency involving: {', '.join(remaining)}"
            )

        return ordered

    async def initialize_all(self, context: SharedContext) -> None:
        for name in self.load_order:
            record = self.records[name]
            context.set_module(name, record.module)
            await record.module.initialize(context)

    async def run_health_checks(self, context: SharedContext) -> dict[str, HealthStatus]:
        """Re-probe every module. Connection requirements always hit live I/O."""
        results: dict[str, HealthStatus] = {}
        for name in self.load_order:
            record = self.records[name]
            module_dep_failures = self._required_module_dep_failures(record.module)
            if module_dep_failures:
                failed = set(module_dep_failures)
                requirements = []
                for req in record.module.requirements:
                    if req.kind is RequirementKind.MODULE and req.name in failed:
                        requirements.append(
                            {
                                "name": req.name,
                                "label": req.label or req.name,
                                "kind": req.kind.value,
                                "required": req.required,
                                "healthy": False,
                                "status": "unhealthy",
                                "message": f"Module '{req.name}' is unhealthy",
                            }
                        )
                    else:
                        requirements.append(
                            {
                                **req.describe(),
                                "healthy": None,
                                "status": "skipped",
                                "message": (
                                    "Not probed because a required module "
                                    "dependency is unhealthy"
                                ),
                            }
                        )
                status = HealthStatus(
                    healthy=False,
                    details={
                        "reason": "required_module_dependency_unhealthy",
                        "failed_dependencies": module_dep_failures,
                    },
                    requirements=requirements,
                )
            else:
                try:
                    status = await record.module.check_health(context)
                except Exception as exc:
                    logger.exception("Health check failed for module %s", name)
                    status = HealthStatus(
                        healthy=False,
                        details={"error": str(exc)},
                    )
            record.health = status
            # Preserve registration state after startup; only flip discovered/healthy.
            if record.state != ModuleState.TOOLS_REGISTERED:
                record.state = (
                    ModuleState.HEALTHY if status.healthy else ModuleState.UNHEALTHY
                )
            results[name] = status
            logger.info(
                "Module %s health: %s",
                name,
                "healthy" if status.healthy else "unhealthy",
            )
        return results

    def _required_module_dep_failures(self, module: BaseModule) -> list[str]:
        failures: list[str] = []
        for req in module.requirements:
            if req.kind is not RequirementKind.MODULE or not req.required:
                continue
            dep_record = self.records.get(req.name)
            if dep_record is None or dep_record.state == ModuleState.UNHEALTHY:
                failures.append(req.name)
            elif dep_record.health is not None and not dep_record.health.healthy:
                failures.append(req.name)
        return failures

    def register_healthy_tools(
        self,
        mcp: MCPServer,
        context: SharedContext,
        *,
        include_unhealthy: bool = False,
    ) -> list[str]:
        """Register tools from newly healthy modules only.

        Modules already in TOOLS_REGISTERED are left alone. Call this after
        every health refresh so dependents that were skipped at bootstrap
        (because a required module was down) get their tools once the
        dependency recovers.

        ``include_unhealthy`` is for unit tests that assert tool presence
        without live databases or APIs.
        """
        registered: list[str] = []
        before = {t.name for t in self._list_tools_sync(mcp)}

        for name in self.load_order:
            record = self.records[name]
            if record.state == ModuleState.TOOLS_REGISTERED:
                continue
            if record.state != ModuleState.HEALTHY and not include_unhealthy:
                logger.warning(
                    "Skipping tool registration for unhealthy module %s", name
                )
                continue
            try:
                record.module.register_tools(mcp, context)
            except Exception as exc:
                record.state = ModuleState.UNHEALTHY
                record.error = str(exc)
                logger.exception("Tool registration failed for module %s", name)
                continue

            after = {t.name for t in self._list_tools_sync(mcp)}
            new_tools = sorted(after - before)
            record.registered_tools = new_tools
            record.state = ModuleState.TOOLS_REGISTERED
            record.error = None
            registered.extend(new_tools)
            before = after
            logger.info(
                "Registered %d tool(s) from module %s: %s",
                len(new_tools),
                name,
                ", ".join(new_tools) or "(none)",
            )

        return registered

    @staticmethod
    def _list_tools_sync(mcp: MCPServer) -> list[Any]:
        # MCPServer keeps tools on the underlying tool manager.
        tools = getattr(mcp, "_tool_manager", None)
        if tools is not None:
            return list(tools.list_tools())
        return []

    def to_dashboard_modules(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for name in self.load_order:
            record = self.records[name]
            module = record.module
            req_results = list(record.health.requirements) if record.health else []
            if not req_results:
                req_results = [
                    {**req.describe(), "healthy": None, "status": "unknown", "message": ""}
                    for req in module.requirements
                ]
            connections = [r for r in req_results if r.get("kind") == "connection"]
            configs = [r for r in req_results if r.get("kind") == "config"]
            modules_req = [r for r in req_results if r.get("kind") == "module"]
            payload.append(
                {
                    "name": module.name,
                    "version": module.version,
                    "state": record.state.value,
                    "healthy": bool(record.health.healthy) if record.health else None,
                    "health_details": record.health.details if record.health else {},
                    "requirements": req_results,
                    "connections": connections,
                    "configs": configs,
                    "module_dependencies": modules_req,
                    # Backward-compatible summary for older clients.
                    "dependencies": [
                        {
                            "name": r.get("name"),
                            "type": r.get("kind"),
                            "required": r.get("required"),
                            "healthy": r.get("healthy"),
                            "status": r.get("status"),
                            "label": r.get("label"),
                            "message": r.get("message"),
                        }
                        for r in req_results
                    ],
                    "registered_tools": list(record.registered_tools),
                    "error": record.error,
                }
            )
        return payload
