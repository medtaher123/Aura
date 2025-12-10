# tests/test_fire_detection_text.py
from fire_detection import extract_params_from_text, detect_fire_tool
import pytest
import json

# Mock LLM responses for extract_params_from_text tests
def mock_llm_response(text):
    """Returns appropriate JSON for different inputs"""
    responses = {
        "Y a-t-il des incendies à Marseille le 2023-07-21 dans un rayon de 50 km ?": {
            "start_date": "2023-07-21", "end_date": "2023-07-21", "location": "Marseille", "radius_km": 50
        },
        "Incendies près de Tunis le 12 août 2021": {
            "start_date": "2021-08-12", "end_date": "2021-08-12", "location": "Tunis", "radius_km": None
        },
        "Potsdam 2024 500": {
            "start_date": "2024-01-01", "end_date": "2024-12-31", "location": "Potsdam", "radius_km": 500
        },
        "Il y a-t-il eu une incendie à Marseille en janvier 2025 dans un rayon de 250 km?": {
            "start_date": "2025-01-01", "end_date": "2025-01-31", "location": "Marseille", "radius_km": 250
        },
        "Marseille en janvier 2025 250": {
            "start_date": "2025-01-01", "end_date": "2025-01-31", "location": "Marseille", "radius_km": 250
        },
        "Marseille 2024-01 - 2024-01 +150": {
            "start_date": "2024-01-01", "end_date": "2024-01-31", "location": "Marseille", "radius_km": 150
        },
        "Marseille janvier 2024 150": {
            "start_date": "2024-01-01", "end_date": "2024-01-31", "location": "Marseille", "radius_km": 150
        },
    }
    return json.dumps(responses.get(text, {}))

@pytest.mark.skip(reason="Requires full Ollama LLM setup")
def test_extract_params_iso_city_radius(mocker):
    mocker.patch('fire_detection.OllamaLLM.invoke', return_value=mock_llm_response(
        "Y a-t-il des incendies à Marseille le 2023-07-21 dans un rayon de 50 km ?"))
    s, e, city, r = extract_params_from_text("Y a-t-il des incendies à Marseille le 2023-07-21 dans un rayon de 50 km ?")
    assert city == "Marseille"
    assert r == 50

@pytest.mark.skip(reason="Requires full Ollama LLM setup")
def test_extract_params_date_fr_no_radius(mocker):
    mocker.patch('fire_detection.OllamaLLM.invoke', return_value=mock_llm_response(
        "Incendies près de Tunis le 12 août 2021"))
    s, e, city, r = extract_params_from_text("Incendies près de Tunis le 12 août 2021")
    assert city == "Tunis"

@pytest.mark.skip(reason="Requires full Ollama LLM setup")
def test_extract_params_year_and_radius_no_keyword(mocker):
    mocker.patch('fire_detection.OllamaLLM.invoke', return_value=mock_llm_response("Potsdam 2024 500"))
    s, e, city, r = extract_params_from_text("Potsdam 2024 500")
    assert city == "Potsdam"

def test_detect_fire_tool_accepts_query_without_keyword(mocker):
    # Mock both the LLM and detect_fire_near_city to avoid network calls
    mocker.patch('fire_detection.OllamaLLM')
    mocker.patch('fire_detection.extract_params_from_text', return_value=('2024-01-01', '2024-12-31', 'Potsdam', 500))
    mocker.patch('fire_detection.detect_fire_near_city', return_value=('fires_potsdam_2024-01-01.html', 2))
    # The detect_fire_tool returns a string, not a dict
    res = detect_fire_tool.invoke('Potsdam 2024 500')
    assert isinstance(res, str)
    assert 'Final Answer' in res
    assert 'Potsdam' in res or 'potsdam' in res.lower()

def test_detect_fire_tool_year_range_aggregation(mocker):
    # Mock the dependencies
    mocker.patch('fire_detection.OllamaLLM')
    mocker.patch('fire_detection.extract_params_from_text', return_value=('2024-01-01', '2024-12-31', 'Potsdam', 500))
    mocker.patch('fire_detection.detect_fire_near_city', return_value=('fires_potsdam_2024-01-01.html', 365))
    res = detect_fire_tool.invoke('Potsdam 2024 500')
    assert isinstance(res, str)
    assert 'Final Answer' in res
    assert 'Potsdam' in res

@pytest.mark.skip(reason="Requires full Ollama LLM setup")
def test_extract_params_month_and_radius(mocker):
    mocker.patch('fire_detection.OllamaLLM.invoke', return_value=mock_llm_response(
        "Il y a-t-il eu une incendie à Marseille en janvier 2025 dans un rayon de 250 km?"))
    s, e, city, r = extract_params_from_text("Il y a-t-il eu une incendie à Marseille en janvier 2025 dans un rayon de 250 km?")
    assert city == "Marseille"

def test_detect_fire_tool_month_range_aggregation(mocker):
    # Mock the dependencies
    mocker.patch('fire_detection.OllamaLLM')
    mocker.patch('fire_detection.extract_params_from_text', return_value=('2025-01-01', '2025-01-31', 'Marseille', 250))
    mocker.patch('fire_detection.detect_fire_near_city', return_value=('fires_marseille_2025-01-01.html', 45))
    res = detect_fire_tool.invoke('Marseille en janvier 2025 250')
    assert isinstance(res, str)
    assert 'Final Answer' in res
    assert 'fire' in res.lower()

def test_detect_fire_tool_text_formats_map_and_message(mocker):
    # Mock the dependencies
    mocker.patch('fire_detection.OllamaLLM')
    mocker.patch('fire_detection.extract_params_from_text', return_value=('2024-01-01', '2024-12-31', 'Potsdam', 500))
    mocker.patch('fire_detection.detect_fire_near_city', return_value=('fires_potsdam_2024-01-01.html', 2))
    res = detect_fire_tool.invoke('Potsdam 2024 500')
    assert isinstance(res, str)
    assert "Final Answer" in res
    assert "fires_potsdam_2024-01-01.html" in res

def test_detect_fire_tool_text_formats_no_map(mocker):
    # Mock detect_fire_near_city to return None (no fires found)
    mocker.patch('fire_detection.OllamaLLM')
    mocker.patch('fire_detection.extract_params_from_text', return_value=('2025-06-01', '2025-06-01', 'Paris', 100))
    mocker.patch('fire_detection.detect_fire_near_city', return_value=None)
    res = detect_fire_tool.invoke('Paris 2025-06-01 100')
    assert isinstance(res, str)
    assert "Final Answer" in res
    assert "no fires detected" in res.lower() or "no fires" in res.lower()

@pytest.mark.skip(reason="Requires full Ollama LLM setup")
def test_extract_params_ym_hyphen_range(mocker):
    mocker.patch('fire_detection.OllamaLLM.invoke', return_value=mock_llm_response(
        "Marseille 2024-01 - 2024-01 +150"))
    s, e, city, r = extract_params_from_text("Marseille 2024-01 - 2024-01 +150")
    assert city == "Marseille"

@pytest.mark.skip(reason="Requires full Ollama LLM setup")
def test_extract_params_month_year_combination(mocker):
    mocker.patch('fire_detection.OllamaLLM.invoke', return_value=mock_llm_response(
        "Marseille janvier 2024 150"))
    s, e, city, r = extract_params_from_text("Marseille janvier 2024 150")
    assert city == "Marseille"

