#weather.py
import requests
from typing import Optional
from langchain.tools import tool

@tool
def weather_tool(city_name: str, forecast_days: Optional[int] = 5) -> str:
    """
    Retrieve current weather and forecasts for a city.
    :param city_name: Name of the city
    :param forecast_days: Number of days to show forecasts for (default 5)
    """
    #  Geocoding via Nominatim 
    geo_url = "https://nominatim.openstreetmap.org/search"
    geo_params = {"q": city_name, "format": "json", "limit": 3}
    geo_resp = requests.get(geo_url, params=geo_params, headers={"User-Agent": "weather-app"})
    geo_data = geo_resp.json()
    
    if not geo_data:
        return f"Final Answer: City '{city_name}' not found."

    lat, lon = float(geo_data[0]["lat"]), float(geo_data[0]["lon"])

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
        return f"Final Answer: Unable to fetch weather data. Status: {weather_resp.status_code}"

    weather_data = weather_resp.json()
    current = weather_data.get("current_weather", {})
    daily = weather_data.get("daily", {})

    # Format result
    result = f"📍 Current weather in {city_name}: {current.get('temperature')}°C, wind {current.get('windspeed')} km/h.\n"
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
    
    return f"Final Answer: {result}"
