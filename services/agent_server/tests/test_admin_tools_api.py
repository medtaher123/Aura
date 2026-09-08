"""Tests for admin tool platform API."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config import get_config
from src.db.base import BaseModel
from src.db.database import get_db
from src.main import app


@pytest.fixture(autouse=True)
def disable_auth(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_config.cache_clear()


@pytest_asyncio.fixture
async def admin_client(monkeypatch, tmp_path):
    db_path = tmp_path / "admin_test.db"
    config_path = tmp_path / "external_mcp_servers.yaml"
    config_path.write_text("mcp_servers: []\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    # Avoid launching real stdio MCP servers (e.g. npx) during unit tests.
    monkeypatch.setenv("EXTERNAL_MCP_CONFIG_FILE", str(config_path))
    get_config.cache_clear()

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    import src.tools.lifecycle.bootstrap as bootstrap_module

    monkeypatch.setattr(bootstrap_module, "AsyncSessionLocal", factory)

    from src.tools.lifecycle.bootstrap import get_tool_platform

    app.dependency_overrides[get_db] = override_get_db
    platform = get_tool_platform()
    platform._state = None
    platform._gateway = None
    await platform.startup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await platform.shutdown()
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_dashboard(admin_client):
    response = await admin_client.get("/admin/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert "mcp_servers" in body
    assert "tools_total" in body
    assert any(s["slug"] == "metaplanet" for s in body["mcp_servers"])


@pytest.mark.asyncio
async def test_admin_ui_page(admin_client):
    response = await admin_client.get("/admin/ui")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert b"Metaplanet Tool Platform" in response.content
    assert b"toggle-enabled" in response.content
    assert b"/admin/ui/tools/" in response.content


@pytest.mark.asyncio
async def test_admin_tool_detail_page(admin_client):
    tools = (await admin_client.get("/admin/tools")).json()
    tool = next(t for t in tools if t["name"] == "get_time")
    page = await admin_client.get(f"/admin/ui/tools/{tool['id']}")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert b"Input schema" in page.content
    assert b"/admin/tools/" in page.content


@pytest.mark.asyncio
async def test_get_tool_detail(admin_client):
    tools = (await admin_client.get("/admin/tools")).json()
    tool = next(t for t in tools if t["name"] == "get_time")
    detail = await admin_client.get(f"/admin/tools/{tool['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["name"] == "get_time"
    assert body["source"] == "native"
    assert "input_schema" in body
    assert isinstance(body["input_schema"], dict)


@pytest.mark.asyncio
async def test_get_tool_detail_not_found(admin_client):
    response = await admin_client.get(
        "/admin/tools/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_mcp_server_removed(admin_client):
    payload = {
        "slug": "test-external",
        "display_name": "Test External MCP",
        "base_url": "http://localhost:9999",
        "enabled": False,
    }
    response = await admin_client.post("/admin/mcp-servers", json=payload)
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_toggle_mcp_server_enabled(admin_client):
    listed = await admin_client.get("/admin/mcp-servers")
    assert listed.status_code == 200
    servers = listed.json()
    assert servers
    server = next(s for s in servers if s["slug"] == "metaplanet")
    assert server["enabled"] is True

    disabled = await admin_client.patch(
        f"/admin/mcp-servers/{server['id']}/enabled",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["tool_count"] == 0

    tools_after = await admin_client.get("/admin/tools")
    assert tools_after.status_code == 200
    mcp_after = {t["name"] for t in tools_after.json() if t["source"] == "mcp"}
    assert mcp_after == set()
    # Native tools remain available.
    native_names = {t["name"] for t in tools_after.json() if t["source"] == "native"}
    assert "get_time" in native_names

    enabled = await admin_client.patch(
        f"/admin/mcp-servers/{server['id']}/enabled",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    tools_restored = await admin_client.get("/admin/tools")
    assert tools_restored.status_code == 200
    # After re-enable, tool_count may be >0 if MCP sync succeeded.
    assert enabled.json()["enabled"] is True
    assert isinstance(enabled.json()["tool_count"], int)



@pytest.mark.asyncio
async def test_list_tools(admin_client):
    response = await admin_client.get("/admin/tools")
    assert response.status_code == 200
    tools = response.json()
    names = {t["name"] for t in tools}
    assert "get_time" in names
    assert "get_date" in names
