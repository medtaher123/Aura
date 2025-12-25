# tests/test_query_hazards_tool.py
import types
import re
import query_hazards_tool as th

def test__get_deterministic_rng_is_stable():
    r1 = th._get_deterministic_rng("Paris, France").random()
    r2 = th._get_deterministic_rng("Paris, France").random()
    assert r1 == r2  # même graine => même tirage

def test_get_top_hazards_shape():
    hazards = th.get_top_hazards("paris, france")
    assert len(hazards) == 5
    for h in hazards:
        assert {"hazard","level"}.issubset(h.keys())
        assert h["level"] in {"High","Medium","Low"}

def test_query_hazards_tool_with_coords_mocks_geopy(mocker):
    # Mock Nominatim.reverse -> objet avec .address
    fake_loc = types.SimpleNamespace(address="Paris, Île-de-France, France")
    mock_nom = mocker.patch("query_hazards_tool.Nominatim")
    mock_nom.return_value.reverse.return_value = fake_loc

    out = th.query_hazards_tool("48.8566, 2.3522")
    assert "Top 5 hazards for this location (Paris, Île-de-France, France):" in out
    # Pas d'appel à geocode si coords
    assert mock_nom.return_value.geocode.call_count == 0
    assert re.search(r"- (River flood|Wildfire|Urban flood|Water scarcity|Extreme heat|Earthquake|Storm surge|Landslide): (High|Medium|Low)", out)

def test_query_hazards_tool_with_name_mocks_geopy(mocker):
    fake_loc = types.SimpleNamespace(address="Tokyo, Japan")
    mock_nom = mocker.patch("query_hazards_tool.Nominatim")
    mock_nom.return_value.geocode.return_value = fake_loc

    out = th.query_hazards_tool("Tokyo")
    assert "Top 5 hazards for this location (Tokyo, Japan):" in out
    assert mock_nom.return_value.reverse.call_count == 0

def test_resolve_location_unknown_returns_string(mocker):
    mock_nom = mocker.patch("query_hazards_tool.Nominatim")
    mock_nom.return_value.geocode.return_value = None
    assert th.resolve_location("qwertyuiop") == "Unknown location"
