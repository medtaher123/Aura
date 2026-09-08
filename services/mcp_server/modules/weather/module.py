"""Weather MCP module: weather forecasts and NASA POWER."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base import BaseModule
from core.requirements import ConnectionRequirement

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext


async def _nasa_power_probe(context) -> bool:
    import httpx

    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(
            url,
            params={
                "parameters": "T2M",
                "community": "RE",
                "longitude": "0",
                "latitude": "0",
                "start": "20200101",
                "end": "20200101",
                "format": "JSON",
            },
        )
        return response.status_code < 500


class WeatherModule(BaseModule):
    name = "weather"
    version = "1.0.0"
    requirements = [
        ConnectionRequirement(
            name="nasa_power",
            probe=_nasa_power_probe,
            required=False,
            label="NASA POWER API",
        ),
    ]

    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        from modules.weather.nasa_power import (
            nasa_power_daily_tool,
            nasa_power_hourly_tool,
        )
        from modules.weather.weather import weather_tool

        for fn in (weather_tool, nasa_power_hourly_tool, nasa_power_daily_tool):
            self.add_tool(mcp, fn)
