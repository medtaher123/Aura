"""
Weather Tool for MCP Server

Retrieves current weather and forecasts for a city using Open-Meteo API.
"""

import requests

from utils.bbox_service import LocationAmbiguousError, get_city_bbox, reverse_geocode
from utils.contracts import ToolCoordinates, ToolResponse

def weather_tool(
    city_name: str | None = None,
    forecast_days: int = 5,
    lat: float | None = None,
    lon: float | None = None,
) -> ToolResponse:
    """Retrieve current weather and forecasts for a city.

    Args:
        city_name: Name of the city (optional if lat/lon provided)
        forecast_days: Number of days to show forecasts for (default 5)
        lat: Latitude of the city
        lon: Longitude of the city
    """
    resolved_city = None
    if lat is not None and lon is not None:
        try:
            lat = float(lat)
            lon = float(lon)
        except Exception:
            return ToolResponse(
                tool_name="weather_tool",
                message="Invalid coordinates provided. lat/lon must be numeric.",
                city=city_name,
                error=True,
            )

        if not isinstance(city_name, str) or not city_name.strip():
            try:
                rev = reverse_geocode(lat, lon)
                resolved_city = rev.get("city") or rev.get("country")
            except Exception:
                resolved_city = None
            city_name = resolved_city or f"{lat:.4f}, {lon:.4f}"
    else:
        if not isinstance(city_name, str) or not city_name.strip():
            return ToolResponse(
                tool_name="weather_tool",
                message="Please provide a city name or lat/lon coordinates.",
                error=True,
            )

        # Geocoding via Nominatim
        try:
            bbox, lat, lon, city_name_final = get_city_bbox(
                city_name, require_confirmation=True
            )
        except LocationAmbiguousError as e:
            return ToolResponse(
                tool_name="weather_tool",
                message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
                city=city_name,
                data={
                    "needs_location_confirmation": True,
                    "location_query": e.query,
                    "candidates": e.candidates,
                    "resume_patch": {"field": "city_name"},
                },
                error=False,
            )

        if lat is None or lon is None:
            return ToolResponse(
                tool_name="weather_tool",
                message=f"City '{city_name}' not found.",
                city=city_name,
                error=True,
            )

        resolved_city = city_name_final or city_name
        city_name = resolved_city

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
        return ToolResponse(
            tool_name="weather_tool",
            message=f"Unable to fetch weather data. Status: {weather_resp.status_code}",
            city=city_name,
            coordinates=ToolCoordinates(lat=float(lat), lon=float(lon)),
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

    return ToolResponse(
        tool_name="weather_tool",
        message=message,
        city=city_name,
        coordinates=ToolCoordinates(lat=float(lat), lon=float(lon)),
        data={
            "current": current,
            "daily": daily,
            "forecast_days": forecast_days,
        },
        error=False,
    )
