# tests/test_stac_queries.py
import json
from datetime import datetime
from tools_risk import query_stac_catalog_with_retry
import tools_risk  # pour monkeypatcher query_stac_catalog

def test_query_stac_catalog_with_retry_finds_on_second_attempt(mocker):
    # Faux STAC: 1er appel -> vide ; 2e appel -> 1 image
    calls = {"i": 0}
    def fake_stac(params):
        calls["i"] += 1
        if calls["i"] == 1:
            return {"message":"Aucune image", "images":[]}
        return {
            "collection":"sentinel-2-l2a",
            "bbox":"-8,33,-7,34",
            "start_date":"2025-09-01",
            "end_date":"2025-09-29",
            "images":[{"date":"2025-09-29","cloud_cover":12.3,"thumbnail":"http://x/t.png"}]
        }

    params = "-8,33,-7,34 2025-09-01 2025-09-30 sentinel-2-l2a"
    out = tools_risk.query_stac_with_retries("-8,33,-7,34","2025-09-01","2025-09-30","sentinel-2-l2a", fake_stac)
    assert out["attempts"] == 2
    assert out["images"]

def test_query_stac_catalog_with_retry_parse_key_value(mocker):
    def fake_stac(_):
        return {"images":[{"date":"2024-01-01"}]}
    mocker.patch("tools_risk.query_stac_catalog", side_effect=fake_stac)
    out = query_stac_catalog_with_retry("lon_min=-8 lat_min=33 lon_max=-7 lat_max=34 start_date=2024-01-01 end_date=2024-01-01 collection=sentinel-2-l2a")
    assert out["images"]