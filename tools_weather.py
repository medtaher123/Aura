#tools_weather.py
from langchain.tools import tool
import requests

@tool
def get_weather_data(city: str = "Tunis") -> str:
    """
    Retrieves current weather for a given city using wttr.in (no API key required).
    - city: city name (e.g., 'Tunis')
    """
    try:
        url = f"https://wttr.in/{city}?format=j1"
        response = requests.get(url)
        if response.status_code != 200:
            return {"message": f"Weather error: {response.status_code} - {response.text}", "downstream_task": "weather", "location": {"city": city}, "error": True}
        data = response.json()
        current = data['current_condition'][0]
        desc = current['weatherDesc'][0]['value']
        temp = current['temp_C']
        return {"message": f"Weather in {city}: {desc}, {temp}°C", "downstream_task": "weather", "location": {"city": city}, "error": False}
    except Exception as e:
        return {"message": f"Error fetching weather data: {str(e)}", "downstream_task": "weather", "location": {"city": city}, "error": True}
