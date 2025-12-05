# tests/test_tools_risk_extract_bbox.py
from tools_risk import extract_bbox_and_dates

def test_extract_bbox_and_dates_minimal(mocker):
    mocker.patch("tools_risk.get_city_bbox", return_value=(-8,33,-7,34,"Casablanca"))
    q = "images satellite de Casablanca en septembre 2025"
    out = extract_bbox_and_dates(q)
    assert out["bbox"] == "-8,33,-7,34"
    assert out["collection"] == "sentinel-2-l2a"
    assert out["start_date"] == "2025-09-01"
    assert out["end_date"] == "2025-09-30"
    assert out["city"] == "Casablanca"

def test_extract_bbox_and_dates_collection_detected(mocker):
    mocker.patch("tools_risk.get_city_bbox", return_value=(10.1,36.7,10.3,36.9,"Tunis"))
    q = "Sentinel-1 de Tunis en mars 2024"
    out = extract_bbox_and_dates(q)
    assert out["collection"] == "sentinel-1-grd"
