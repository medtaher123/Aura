"""Tests for Metaplanet + external MCP config reconcile."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config import get_config
from src.db.base import BaseModel
from src.db.repositories.tool_platform import McpServerRepository
from src.tools.lifecycle.external_mcp import (
    ExternalMcpReconciler,
    expand_env,
    load_external_mcp_config,
    resolve_node_runner_base_url,
)
from src.tools.providers.factory import build_mcp_provider
from src.tools.providers.mcp import McpToolProvider
from src.tools.providers.metaplanet import (
    METAPLANET_MCP_SLUG,
    MetaplanetMcpProvider,
)


@pytest.fixture
def external_mcp_yaml(tmp_path: Path) -> Path:
    document = {
        "mcp_servers": [
            {
                "slug": "metaplanet",
                "display_name": "Should Be Ignored",
                "base_url": "http://ignored:1",
                "is_primary": True,
            },
            {
                "slug": "external",
                "display_name": "External MCP",
                "base_url": "http://localhost:9999",
                "enabled": False,
            },
        ],
    }
    path = tmp_path / "external_mcp_servers.yaml"
    path.write_text(yaml.dump(document), encoding="utf-8")
    return path


@pytest_asyncio.fixture
async def db_session(tmp_path):
    db_path = tmp_path / "external_mcp_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_expand_env_mcp_server_url(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://example:9000")
    assert expand_env("${MCP_SERVER_URL}") == "http://example:9000"


def test_load_default_external_mcp_config(monkeypatch):
    monkeypatch.delenv("NODE_MCP_URL", raising=False)
    get_config.cache_clear()
    path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "external_mcp_servers.yaml"
    )
    assert path.is_file()
    document = load_external_mcp_config(path)
    slugs = [s["slug"] for s in document["mcp_servers"]]
    assert slugs == ["ign-geocontext", "ign-carto", "immo-france"]
    assert "native_tools" not in document
    assert "agent_profiles" not in document
    assert all(s["slug"] != "metaplanet" for s in document["mcp_servers"])
    assert document["mcp_servers"][0]["base_url"].endswith("/geocontext")
    assert document["mcp_servers"][1]["base_url"].endswith("/carto")
    immo = document["mcp_servers"][2]
    assert immo["runner"] == "node"
    assert immo["port"] == 8101
    assert immo["transport"] == "streamable_http"


def test_resolve_node_runner_base_url(monkeypatch):
    monkeypatch.setenv("NODE_MCP_URL", "http://node-mcp")
    assert resolve_node_runner_base_url(8101) == "http://node-mcp:8101"

    monkeypatch.setenv("NODE_MCP_URL", "http://localhost")
    assert resolve_node_runner_base_url(8101) == "http://localhost:8101"


@pytest.mark.asyncio
async def test_reconcile_node_runner_server(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp:8000")
    monkeypatch.setenv("NODE_MCP_URL", "http://node-mcp")
    get_config.cache_clear()
    path = tmp_path / "node_external.yaml"
    path.write_text(
        yaml.dump(
            {
                "mcp_servers": [
                    {
                        "slug": "immo-france",
                        "display_name": "Immo France",
                        "runner": "node",
                        "port": 8101,
                        "transport": "streamable_http",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reconciler = ExternalMcpReconciler(config_path=path)
    result = await reconciler.reconcile(db_session)
    assert result.created == 2

    immo = await McpServerRepository(db_session).get_by_slug("immo-france")
    assert immo is not None
    assert immo.transport == "streamable_http"
    assert immo.base_url == "http://node-mcp:8101"


@pytest.mark.asyncio
async def test_reconcile_stdio_server(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp:8000")
    get_config.cache_clear()
    path = tmp_path / "stdio_external.yaml"
    path.write_text(
        yaml.dump(
            {
                "mcp_servers": [
                    {
                        "slug": "legacy-stdio",
                        "display_name": "Legacy Stdio",
                        "transport": "stdio",
                        "command": "npx",
                        "args": ["-y", "some-mcp"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reconciler = ExternalMcpReconciler(config_path=path)
    result = await reconciler.reconcile(db_session)
    assert result.created == 2  # metaplanet + legacy-stdio

    legacy = await McpServerRepository(db_session).get_by_slug("legacy-stdio")
    assert legacy is not None
    assert legacy.transport == "stdio"
    assert legacy.stdio_config["command"] == "npx"
    assert legacy.stdio_config["args"] == ["-y", "some-mcp"]
    assert legacy.base_url == "stdio://legacy-stdio"


def test_build_mcp_provider_types():
    from types import SimpleNamespace
    from uuid import uuid4

    primary = SimpleNamespace(
        id=uuid4(),
        slug=METAPLANET_MCP_SLUG,
        base_url="http://localhost:8000",
        transport="streamable_http",
        auth_headers={},
        stdio_config={},
        is_primary=True,
    )
    external = SimpleNamespace(
        id=uuid4(),
        slug="external",
        base_url="http://localhost:9999",
        transport="streamable_http",
        auth_headers={},
        stdio_config={},
        is_primary=False,
    )
    assert isinstance(build_mcp_provider(primary), MetaplanetMcpProvider)
    assert isinstance(build_mcp_provider(external), McpToolProvider)
    assert not isinstance(build_mcp_provider(external), MetaplanetMcpProvider)


@pytest.mark.asyncio
async def test_reconcile_ensures_metaplanet_and_external(
    db_session, external_mcp_yaml, monkeypatch
):
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp-from-config:8000")
    get_config.cache_clear()

    reconciler = ExternalMcpReconciler(config_path=external_mcp_yaml)
    result = await reconciler.reconcile(db_session)
    assert result.created == 2  # metaplanet + external
    assert result.updated == 0

    servers = await McpServerRepository(db_session).list()
    by_slug = {s.slug: s for s in servers}
    assert set(by_slug) == {"metaplanet", "external"}
    assert by_slug["metaplanet"].is_primary is True
    assert by_slug["metaplanet"].base_url == "http://mcp-from-config:8000"
    assert by_slug["metaplanet"].display_name == "Metaplanet MCP"
    assert by_slug["external"].enabled is False
    assert by_slug["external"].is_primary is False


@pytest.mark.asyncio
async def test_reconcile_preserves_enabled_and_updates_external(
    db_session, external_mcp_yaml, monkeypatch
):
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp:8000")
    get_config.cache_clear()

    reconciler = ExternalMcpReconciler(config_path=external_mcp_yaml)
    await reconciler.reconcile(db_session)

    repo = McpServerRepository(db_session)
    primary = await repo.get_by_slug("metaplanet")
    assert primary is not None
    primary.enabled = False
    await repo.commit()

    # Change external display name / URL in YAML; Metaplanet entry stays ignored.
    document = yaml.safe_load(external_mcp_yaml.read_text(encoding="utf-8"))
    document["mcp_servers"][1]["display_name"] = "External Renamed"
    document["mcp_servers"][1]["base_url"] = "http://external-renamed:8000"
    document["mcp_servers"][1]["enabled"] = True
    external_mcp_yaml.write_text(yaml.dump(document), encoding="utf-8")

    # Point Metaplanet at a new config URL.
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp-renamed:8000")
    get_config.cache_clear()

    result = await reconciler.reconcile(db_session)
    assert result.created == 0
    assert result.updated == 2  # metaplanet URL + external definition

    refreshed_primary = await repo.get_by_slug("metaplanet")
    assert refreshed_primary is not None
    assert refreshed_primary.base_url == "http://mcp-renamed:8000"
    assert refreshed_primary.enabled is False

    refreshed_ext = await repo.get_by_slug("external")
    assert refreshed_ext is not None
    assert refreshed_ext.display_name == "External Renamed"
    assert refreshed_ext.base_url == "http://external-renamed:8000"
    assert refreshed_ext.enabled is False  # preserved
