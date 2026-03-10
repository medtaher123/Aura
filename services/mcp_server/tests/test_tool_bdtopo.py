"""Tests for BDTOPO PostGIS MCP tool."""

from __future__ import annotations

import pytest

from tools import bdtopo as bd


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bdtopo_tool_is_registered(mcp_client):
    tools = await mcp_client.list_tools()
    names = [tool["name"] for tool in tools]
    assert "bdtopo_query_tool" in names


@pytest.mark.unit
def test_bdtopo_unsupported_query_type():
    result = bd.bdtopo_query_tool(
        query_type="unknown_query",
        lat=48.8566,
        lon=2.3522,
    )
    assert result.error is True
    assert "Unsupported query_type" in result.message
    assert "supported_query_types" in result.data
    assert "admin_lookup" in result.data["supported_query_types"]


@pytest.mark.unit
def test_bdtopo_admin_lookup_success(monkeypatch):
    def fake_run_query(_sql, _params):
        return [
            {
                "source_table": "commune",
                "object_id": "abc123",
                "label": "Paris",
                "code_insee": "75056",
                "population": 2000000,
            }
        ]

    monkeypatch.setattr(bd, "_run_query", fake_run_query)
    result = bd.bdtopo_query_tool(
        query_type="admin_lookup",
        lat=48.8566,
        lon=2.3522,
    )
    assert result.error is False
    assert result.data["matches"][0]["label"] == "Paris"
    assert result.data["summary"]["code_insee"] == "75056"
    assert result.artifacts.urls
    assert result.artifacts.maps


@pytest.mark.unit
def test_bdtopo_missing_database(monkeypatch):
    from tools import bdtopo_common
    monkeypatch.setattr(bdtopo_common, "resolve_database_url", lambda: "")
    result = bd.bdtopo_query_tool(
        query_type="named_places",
        lat=48.8566,
        lon=2.3522,
    )
    assert result.error is True
    assert "BDTOPO database is not configured" in result.message

