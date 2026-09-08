"""Tests for Requirement probes (config vs connection)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.context import SharedContext
from core.requirements import (
    ConfigRequirement,
    ConnectionRequirement,
    ModuleRequirement,
)


class _Cfg:
    empty = ""
    key = "secret"
    db_url = "postgresql://example"


@pytest.mark.asyncio
async def test_config_requirement_configured():
    ctx = SharedContext(_Cfg())
    req = ConfigRequirement(name="api_key", config_attr="key", label="API key")
    result = await req.check(ctx)
    assert result.healthy is True
    assert result.status == "configured"


@pytest.mark.asyncio
async def test_config_requirement_missing_optional():
    ctx = SharedContext(_Cfg())
    req = ConfigRequirement(
        name="missing", config_attr="empty", required=False, label="Missing"
    )
    result = await req.check(ctx)
    assert result.status == "not_configured"
    assert result.healthy is True


@pytest.mark.asyncio
async def test_config_requirement_missing_required():
    ctx = SharedContext(_Cfg())
    req = ConfigRequirement(
        name="missing", config_attr="empty", required=True, label="Missing"
    )
    result = await req.check(ctx)
    assert result.status == "not_configured"
    assert result.healthy is False


@pytest.mark.asyncio
async def test_connection_skips_probe_when_not_configured():
    called = {"n": 0}

    def probe(_ctx):
        called["n"] += 1
        return True

    ctx = SharedContext(_Cfg())
    req = ConnectionRequirement(
        name="db",
        config_attr="empty",
        probe=probe,
        required=False,
        label="DB",
    )
    result = await req.check(ctx)
    assert result.status == "not_configured"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_connection_probes_when_configured():
    called = {"n": 0}

    def probe(_ctx):
        called["n"] += 1
        return True

    ctx = SharedContext(_Cfg())
    req = ConnectionRequirement(
        name="db",
        config_attr="db_url",
        probe=probe,
        required=True,
        label="DB",
    )
    result = await req.check(ctx)
    assert result.status == "ok"
    assert result.healthy is True
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_connection_unhealthy_on_probe_failure():
    def probe(_ctx):
        raise RuntimeError("refused")

    ctx = SharedContext(_Cfg())
    req = ConnectionRequirement(
        name="db",
        config_attr="db_url",
        probe=probe,
        required=False,
        label="DB",
    )
    result = await req.check(ctx)
    assert result.status == "unhealthy"
    assert result.healthy is False
    assert "refused" in result.message


@pytest.mark.asyncio
async def test_module_requirement_missing():
    ctx = SharedContext(_Cfg())
    ctx.registry = SimpleNamespace(records={})
    req = ModuleRequirement(name="geospatial", required=True)
    result = await req.check(ctx)
    assert result.status == "missing"
    assert result.healthy is False
