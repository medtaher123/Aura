"""Tests for Streamlit bounding-box input helpers."""

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "ui" / "bbox_input.py"
_SPEC = importlib.util.spec_from_file_location("bbox_input", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_bbox_input = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_bbox_input)
geojson_feature_to_bbox = _bbox_input.geojson_feature_to_bbox
bounding_box_attachment = _bbox_input.bounding_box_attachment
bbox_from_folium_draw_output = _bbox_input.bbox_from_folium_draw_output


def test_geojson_feature_to_bbox():
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [2.0, 48.0],
                    [3.0, 48.0],
                    [3.0, 49.0],
                    [2.0, 49.0],
                    [2.0, 48.0],
                ]
            ],
        },
    }
    bbox = geojson_feature_to_bbox(feature)
    assert bbox == [48.0, 49.0, 2.0, 3.0]
    payload = bounding_box_attachment(bbox)
    assert payload["type"] == "bounding_box"
    assert payload["area"]["min_lat"] == 48.0
    assert payload["area"]["kind"] == "bounding_box"


def test_geojson_feature_to_bbox_rejects_non_polygon():
    assert geojson_feature_to_bbox({"geometry": {"type": "Point", "coordinates": [1, 2]}}) is None
    assert geojson_feature_to_bbox(None) is None


def test_bbox_from_folium_draw_output_prefers_last_active():
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[2.0, 48.0], [3.0, 48.0], [3.0, 49.0], [2.0, 49.0], [2.0, 48.0]]
            ],
        },
    }
    assert bbox_from_folium_draw_output({"last_active_drawing": feature}) == [
        48.0,
        49.0,
        2.0,
        3.0,
    ]
    assert bbox_from_folium_draw_output({"all_drawings": [feature]}) == [
        48.0,
        49.0,
        2.0,
        3.0,
    ]
    assert bbox_from_folium_draw_output({}) is None
