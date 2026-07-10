"""Tests for TerraZard flood briefing MCP tool."""

from __future__ import annotations

import pytest

from tools.terrazard.briefing_service import FloodBriefing
from utils.contracts import ToolArtifacts, ToolCoordinates


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terrazard_flood_briefing_tool_exists(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "get_terrazard_flood_briefing_tool" in tool_names


@pytest.mark.unit
def test_flood_briefing_tool_requires_dates():
    from tools.terrazard.terrazard_flood_briefing import get_terrazard_flood_briefing_tool

    result = get_terrazard_flood_briefing_tool(
        start_date="",
        end_date="20241231",
        lat=48.8566,
        lon=2.3522,
    )
    assert result.error is True


@pytest.mark.unit
def test_flood_briefing_tool_success(monkeypatch):
    from tools.terrazard import terrazard_flood_briefing as mod

    monkeypatch.setattr(
        mod,
        "resolve_spatial_context",
        lambda *_args, **_kwargs: (
            ToolCoordinates(lat=48.8566, lon=2.3522),
            [48.80, 48.90, 2.20, 2.45],
            "Paris",
        ),
    )

    class StubBriefingService:
        def build(self, **_kwargs):
            return FloodBriefing(
                agent_briefing={
                    "headline": "Major event for Paris on 2024-03-15",
                    "recommended_date": "20240315",
                    "severity": {"tier": "major", "water_count": 42},
                },
                message="TerraZard flood briefing for Paris on 2024-03-15.",
                recommended_date="20240315",
                available_dates=[{"date": "20240315", "water_count": 42}],
                artifacts=ToolArtifacts(),
            )

    monkeypatch.setattr(mod, "BriefingService", lambda: StubBriefingService())

    result = mod.get_terrazard_flood_briefing_tool(
        start_date="2024-01-01",
        end_date="2024-12-31",
        lat=48.8566,
        lon=2.3522,
    )

    assert result.error is False
    assert result.data["agent_briefing"]["severity"]["tier"] == "major"
    assert result.data["recommended_date"] == "20240315"
