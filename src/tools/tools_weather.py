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
            return f"Final Answer: Weather error: {response.status_code} - {response.text}"
        data = response.json()
        current = data['current_condition'][0]
        desc = current['weatherDesc'][0]['value']
        temp = current['temp_C']
        return f"Final Answer: Weather in {city}: {desc}, {temp}°C"
    except Exception as e:
        return f"Final Answer: Error fetching weather data: {str(e)}"
