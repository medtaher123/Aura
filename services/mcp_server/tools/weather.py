"""
Weather Tool for MCP Server

Retrieves current weather and forecasts for a city using Open-Meteo API.
"""

import requests

from utils.bbox_service import LocationAmbiguousError, get_city_bbox
from utils.contracts import make_tool_response
from mcp_singleton import mcp


@mcp.tool()
def weather_tool(city_name: str, forecast_days: int = 5) -> dict:
    """Retrieve current weather and forecasts for a city.

    Args:
        city_name: Name of the city
        forecast_days: Number of days to show forecasts for (default 5)
    """
    # Geocoding via Nominatim
    try:
        bbox, lat, lon, city_name_final = get_city_bbox(
            city_name, require_confirmation=True
        )
    except LocationAmbiguousError as e:
        return make_tool_response(
            tool_name="weather_tool",
            message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
            city=city_name,
            data={
                "needs_location_confirmation": True,
                "location_query": e.query,
                "candidates": e.candidates,
                "resume_patch": {"field": "city_name"},
            },
            error=True,
        )

    if not lat or not lon:
        return make_tool_response(
            tool_name="weather_tool",
            message=f"City '{city_name}' not found.",
            city=city_name,
            error=True,
        )

    # Call Open-Meteo API
    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
        ],
        "timezone": "auto",
    }
    weather_resp = requests.get(weather_url, params=weather_params)
    if weather_resp.status_code != 200:
        return make_tool_response(
            tool_name="weather_tool",
            message=f"Unable to fetch weather data. Status: {weather_resp.status_code}",
            city=city_name,
            coordinates={"lat": float(lat), "lon": float(lon)},
            error=True,
        )

    weather_data = weather_resp.json()
    current = weather_data.get("current_weather", {})
    daily = weather_data.get("daily", {})

    # Format result
    message = (
        f"📍 Current weather in {city_name}: {current.get('temperature')}°C, "
        f"wind {current.get('windspeed')} km/h.\n"
    )
    message += f"\nForecast for the next {forecast_days} days:\n"

    days_left = forecast_days
    for date_str, tmax, tmin, rain in zip(
        daily.get("time", []),
        daily.get("temperature_2m_max", []),
        daily.get("temperature_2m_min", []),
        daily.get("precipitation_sum", []),
    ):
        message += f"{date_str} : Max {tmax}°C / Min {tmin}°C / Rain {rain} mm\n"
        days_left -= 1
        if days_left == 0:
            break

    return make_tool_response(
        tool_name="weather_tool",
        message=message,
        city=city_name,
        coordinates={"lat": float(lat), "lon": float(lon)},
        data={
            "current": current,
            "daily": daily,
            "forecast_days": forecast_days,
        },
        error=False,
    )
