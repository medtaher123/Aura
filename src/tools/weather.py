import requests
from typing import Optional
from langchain.tools import tool
from src.services.bbox_service import LocationAmbiguousError, get_city_bbox
from .contracts import make_tool_response

@tool("weather_tool", return_direct=True)
def weather_tool(city_name: str, forecast_days: Optional[int] = 5) -> dict:
    """
    Retrieve current weather and forecasts for a city.
    :param city_name: Name of the city
    :param forecast_days: Number of days to show forecasts for (default 5)
    example: weather_tool("Paris", 3)
    """
    #  Geocoding via Nominatim
    try:
        bbox, lat, lon, city_name_final = get_city_bbox(city_name, require_confirmation=True)
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


    # Appel API Open-Meteo
    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"],
        "timezone": "auto"
    }
    weather_resp = requests.get(weather_url, params=weather_params)
    if weather_resp.status_code != 200:
        return make_tool_response(
            tool_name="weather_tool",
            message=f"Unable to fetch weather data. Status: {weather_resp.status_code}",
            city=city_name,
            coordinates={"lat": lat, "lon": lon},
            error=True,
        )

    weather_data = weather_resp.json()
    current = weather_data.get("current_weather", {})
    daily = weather_data.get("daily", {})

    # Format result
    result = (
        f"📍 Current weather in {city_name}: {current.get('temperature')}°C, "
        f"wind {current.get('windspeed')} km/h.\n"
    )
    result += f"\nForecast for the next {forecast_days} days:\n"
    
    days_left = forecast_days
    for date, tmax, tmin, rain in zip(
        daily.get("time", []),
        daily.get("temperature_2m_max", []),
        daily.get("temperature_2m_min", []),
        daily.get("precipitation_sum", [])
    ):
        result += f"{date} : Max {tmax}°C / Min {tmin}°C / Rain {rain} mm\n"
        days_left -= 1
        if days_left == 0:
            break
    
    return make_tool_response(
        tool_name="weather_tool",
        message=result,
        city=city_name,
        coordinates={"lat": lat, "lon": lon},
        data={"current": current, "daily": daily, "forecast_days": forecast_days},
        error=False,
    )
