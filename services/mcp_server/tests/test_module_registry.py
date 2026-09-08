"""Tests for ModuleRegistry discovery and topological sorting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.base import BaseModule, HealthStatus
from core.context import SharedContext
from core.registry import ModuleRecord, ModuleRegistry, ModuleState
from core.requirements import ModuleRequirement


class _Alpha(BaseModule):
    name = "alpha"
    version = "1.0.0"
    requirements = []

    def __init__(self) -> None:
        self.healthy = True
        self.register_calls = 0

    async def check_health(self, context):
        return HealthStatus(healthy=self.healthy, details={})

    def register_tools(self, mcp, context):
        self.register_calls += 1
        self.add_tool(mcp, SimpleNamespace(name="alpha_tool"))


class _Beta(BaseModule):
    name = "beta"
    version = "1.0.0"
    requirements = [
        ModuleRequirement(name="alpha", required=True),
    ]

    def __init__(self) -> None:
        self.register_calls = 0

    async def check_health(self, context):
        return HealthStatus(healthy=True, details={})

    def register_tools(self, mcp, context):
        self.register_calls += 1
        self.add_tool(mcp, SimpleNamespace(name="beta_tool"))


class _FakeToolManager:
    def __init__(self) -> None:
        self._tools: dict[str, object] = {}

    def list_tools(self) -> list[object]:
        return list(self._tools.values())


class _FakeMcp:
    def __init__(self) -> None:
        self._tool_manager = _FakeToolManager()
        self.added_meta: dict[str, dict] = {}

    def add_tool(self, fn: object, meta: dict | None = None, **_kwargs) -> None:
        name = getattr(fn, "name", None) or getattr(fn, "__name__", str(fn))
        self._tool_manager._tools[name] = SimpleNamespace(name=name, meta=meta)
        if meta is not None:
            self.added_meta[name] = meta


class _CycleA(BaseModule):
    name = "cycle_a"
    version = "1.0.0"
    requirements = [
        ModuleRequirement(name="cycle_b", required=True),
    ]

    async def check_health(self, context):
        return HealthStatus(healthy=True, details={})

    def register_tools(self, mcp, context):
        return None


class _CycleB(BaseModule):
    name = "cycle_b"
    version = "1.0.0"
    requirements = [
        ModuleRequirement(name="cycle_a", required=True),
    ]

    async def check_health(self, context):
        return HealthStatus(healthy=True, details={})

    def register_tools(self, mcp, context):
        return None


def test_topo_sort_orders_module_dependencies():
    registry = ModuleRegistry()
    registry.records = {
        "alpha": ModuleRecord(module=_Alpha()),
        "beta": ModuleRecord(module=_Beta()),
    }
    order = registry.resolve_dependency_order()
    assert order.index("alpha") < order.index("beta")


def test_topo_sort_detects_cycles():
    registry = ModuleRegistry()
    registry.records = {
        "cycle_a": ModuleRecord(module=_CycleA()),
        "cycle_b": ModuleRecord(module=_CycleB()),
    }
    with pytest.raises(RuntimeError, match="Circular"):
        registry.resolve_dependency_order()


def test_discover_real_modules():
    registry = ModuleRegistry(package_name="modules")
    modules = registry.discover_and_load()
    names = {m.name for m in modules}
    assert names == {
        "utility",
        "hazards",
        "weather",
        "imagery",
        "geospatial",
        "flood",
    }
    assert registry.load_order.index("geospatial") < registry.load_order.index("flood")


@pytest.mark.asyncio
async def test_geospatial_initialize_creates_missing_cleabs_index(monkeypatch):
    from modules.geospatial.module import (
        _BATIMENT_ANALYZE_SQL,
        GeospatialModule,
        _BATIMENT_CLEABS_INDEX,
        _BATIMENT_CLEABS_INDEX_DDL,
    )

    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __init__(self):
            self._fetchone = None

        def execute(self, sql, params=None):
            executed.append((str(sql), params))
            if "FROM pg_indexes" in str(sql):
                self._fetchone = None

        def fetchone(self):
            return self._fetchone

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "modules.geospatial.module.resolve_database_url",
        lambda: "postgresql://example",
    )
    monkeypatch.setattr(
        "modules.geospatial.module.psycopg.connect",
        lambda *args, **kwargs: FakeConnection(),
    )

    await GeospatialModule().initialize(SharedContext(config=SimpleNamespace()))

    assert any("FROM pg_indexes" in sql for sql, _ in executed)
    assert any(sql == _BATIMENT_CLEABS_INDEX_DDL for sql, _ in executed)
    assert any(sql == _BATIMENT_ANALYZE_SQL for sql, _ in executed)
    assert executed[0][1] == (_BATIMENT_CLEABS_INDEX,)


@pytest.mark.asyncio
async def test_geospatial_initialize_skips_existing_cleabs_index(monkeypatch):
    from modules.geospatial.module import GeospatialModule

    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((str(sql), params))

        def fetchone(self):
            return (1,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "modules.geospatial.module.resolve_database_url",
        lambda: "postgresql://example",
    )
    monkeypatch.setattr(
        "modules.geospatial.module.psycopg.connect",
        lambda *args, **kwargs: FakeConnection(),
    )

    await GeospatialModule().initialize(SharedContext(config=SimpleNamespace()))

    assert len(executed) == 1
    assert "FROM pg_indexes" in executed[0][0]


@pytest.mark.asyncio
async def test_dependent_tools_register_after_dependency_recovers():
    """If a required module is down at bootstrap, dependents get tools on recovery."""
    alpha = _Alpha()
    beta = _Beta()
    alpha.healthy = False

    registry = ModuleRegistry()
    registry.records = {
        "alpha": ModuleRecord(module=alpha),
        "beta": ModuleRecord(module=beta),
    }
    registry.load_order = registry.resolve_dependency_order()

    context = SharedContext(config=SimpleNamespace())
    context.registry = registry
    mcp = _FakeMcp()

    await registry.run_health_checks(context)
    first = registry.register_healthy_tools(mcp, context)
    assert first == []
    assert registry.records["alpha"].state == ModuleState.UNHEALTHY
    assert registry.records["beta"].state == ModuleState.UNHEALTHY
    assert alpha.register_calls == 0
    assert beta.register_calls == 0

    alpha.healthy = True
    await registry.run_health_checks(context)
    recovered = registry.register_healthy_tools(mcp, context)

    assert recovered == ["alpha_tool", "beta_tool"]
    assert registry.records["alpha"].state == ModuleState.TOOLS_REGISTERED
    assert registry.records["beta"].state == ModuleState.TOOLS_REGISTERED
    assert alpha.register_calls == 1
    assert beta.register_calls == 1

    # Idempotent: already-registered modules are not re-registered.
    await registry.run_health_checks(context)
    assert registry.register_healthy_tools(mcp, context) == []
    assert alpha.register_calls == 1
    assert beta.register_calls == 1

    assert mcp.added_meta["alpha_tool"] == {
        "module": "alpha",
        "module_version": "1.0.0",
    }
    assert mcp.added_meta["beta_tool"]["module"] == "beta"
