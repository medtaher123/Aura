# tests/test_itinerary_helpers.py
from itinerary import human_distance, human_duration, format_step

def test_human_distance():
    assert human_distance(999) == "999 m"
    assert human_distance(1200) == "1.2 km"

def test_human_duration():
    assert human_duration(59*60) == "59 min"
    assert human_duration(60*60) == "1 h"
    assert human_duration(90*60) == "1 h 30 min"

def test_format_step_turn():
    step = {"maneuver":{"type":"turn","modifier":"right"},"name":"Rue X","distance":120}
    result = format_step(step)
    # Function returns English format, not French
    assert "Turn right sur Rue X (120 m)." in result
