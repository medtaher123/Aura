# tests/test_fire_detection_text.py
from fire_detection import extract_params_from_text

def test_extract_params_iso_city_radius():
    s, e, city, r = extract_params_from_text("Y a-t-il des incendies à Marseille le 2023-07-21 dans un rayon de 50 km ?")
    assert s == "2023-07-21"
    assert e == "2023-07-21"
    assert city == "Marseille"
    assert r == 50

def test_extract_params_date_fr_no_radius():
    s, e, city, r = extract_params_from_text("Incendies près de Tunis le 12 août 2021")
    assert s == "2021-08-12"
    assert e == "2021-08-12"
    assert city == "Tunis"
    assert r == 100  # défaut

def test_extract_params_year_and_radius_no_keyword():
    s, e, city, r = extract_params_from_text("Potsdam 2024 500")
    assert city == "Potsdam"
    assert s == "2024-01-01"
    assert e == "2024-12-31"
    assert r == 500

def test_detect_fire_tool_accepts_query_without_keyword(mocker):
    # Patch detect_fire_near_city to avoid network calls
    mocker.patch('fire_detection.detect_fire_near_city', return_value=('fires_potsdam_2024-01-01.html', 2))
    from fire_detection import detect_fire_tool
    # Call the underlying function directly
    res = detect_fire_tool.func('Potsdam 2024 500') if hasattr(detect_fire_tool, 'func') else detect_fire_tool.invoke(('Potsdam 2024 500',))
    assert isinstance(res, dict)
    assert res.get('error') is False
    assert 'Potsdam' in res.get('message') or 'potsdam' in res.get('message').lower()

def test_detect_fire_tool_year_range_aggregation(mocker):
    # Mock detect_fire_near_city to return only for specific dates
    def fake_detect(date_str, city, radius):
        if date_str in ("2024-03-01", "2024-03-02"):
            return (f"fires_{city.lower()}_{date_str}.html", 1)
        return None

    mocker.patch('fire_detection.detect_fire_near_city', side_effect=fake_detect)
    from fire_detection import detect_fire_tool
    # call for year 2024
    res = detect_fire_tool.func('Potsdam 2024 500') if hasattr(detect_fire_tool, 'func') else detect_fire_tool.invoke(('Potsdam 2024 500',))
    assert isinstance(res, dict)
    assert res.get('error') is False
    assert res.get('fires_detected') == 2


def test_extract_params_month_and_radius():
    s, e, city, r = extract_params_from_text("Il y a-t-il eu une incendie à Marseille en janvier 2025 dans un rayon de 250 km?")
    assert s == "2025-01-01"
    assert e == "2025-01-31"
    assert city == "Marseille"
    assert r == 250


def test_detect_fire_tool_month_range_aggregation(mocker):
    # Mock detect_fire_near_city to return only for specific dates
    def fake_detect(date_str, city, radius):
        if date_str in ("2025-01-01", "2025-01-02"):
            return (f"fires_{city.lower()}_{date_str}.html", 1)
        return None

    mocker.patch('fire_detection.detect_fire_near_city', side_effect=fake_detect)
    from fire_detection import detect_fire_tool
    res = detect_fire_tool.func('Marseille en janvier 2025 250') if hasattr(detect_fire_tool, 'func') else detect_fire_tool('Marseille en janvier 2025 250')
    assert isinstance(res, dict)
    assert res.get('error') is False
    # Should detect 2 fires (on 1 and 2 Jan)
    assert res.get('fires_detected') == 2


def test_detect_fire_tool_text_formats_map_and_message(mocker):
    # Prepare a fake tool with a .func attribute (simulates langchain tool wrapper)
    fake_res = {"message": "2 fires detected around Potsdam", "map_file": "fires_potsdam_2024-01-01.html"}

    class FakeTool:
        def func(self, q):
            return fake_res

    mocker.patch('fire_detection.detect_fire_tool', FakeTool())
    from fire_detection import detect_fire_tool_text
    rtxt = detect_fire_tool_text('Potsdam 2024 500')
    assert isinstance(rtxt, str)
    assert "Final Answer" in rtxt
    assert "Map: fires_potsdam_2024-01-01.html" in rtxt


def test_detect_fire_tool_text_formats_no_map(mocker):
    fake_res = {"message": "No fires found in Paris"}

    class FakeTool2:
        def func(self, q):
            return fake_res

    mocker.patch('fire_detection.detect_fire_tool', FakeTool2())
    from fire_detection import detect_fire_tool_text
    rtxt = detect_fire_tool_text('Paris 2025-06-01 100')
    assert isinstance(rtxt, str)
    assert "Final Answer: No fires found in Paris" in rtxt


def test_extract_params_ym_hyphen_range():
    s, e, city, r = extract_params_from_text("Marseille 2024-01 - 2024-01 +150")
    assert s == "2024-01-01"
    assert e == "2024-01-31"
    assert city == "Marseille"
    assert r == 150


def test_extract_params_month_year_combination():
    s, e, city, r = extract_params_from_text("Marseille janvier 2024 150")
    assert s == "2024-01-01"
    assert e == "2024-01-31"
    assert city == "Marseille"
    assert r == 150
