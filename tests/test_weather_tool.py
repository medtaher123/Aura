import pytest
from weather import weather_tool

def test_weather_tool_ok(mocker):
    # Mock Nominatim
    m_geo = mocker.Mock()
    m_geo.json.return_value = [{"lat": "48.8566", "lon": "2.3522"}]
    # Mock Open-Meteo
    m_w = mocker.Mock()
    m_w.status_code = 200
    m_w.json.return_value = {
        "current_weather": {"temperature": 18, "windspeed": 12},
        "daily": {
            "time": ["2025-09-01", "2025-09-02"],
            "temperature_2m_max": [23, 24],
            "temperature_2m_min": [14, 15],
            "precipitation_sum": [0, 1]
        }
    }

    def fake_get(url, params=None, headers=None):
        if "nominatim.openstreetmap.org/search" in url:
            return m_geo
        return m_w

    mocker.patch("weather.requests.get", side_effect=fake_get)

    # 🩵 Appel correct de la fonction Python
    if hasattr(weather_tool, "func"):
        out = weather_tool.func("Paris", 2)
    else:
        out = weather_tool.invoke(("Paris", 2))

    # ✅ Verify we get a structured dict result with a message string
    assert isinstance(out, dict)
    msg = out.get("message", "")
    assert "Paris" in msg
    assert "Météo actuelle" in msg or "weather" in msg.lower()
