"""Tests for Streamlit location attach helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

# location_input imports get_osm_type_prefix from agent_ws_client; stub it.
_stub = ModuleType("src")
_clients = ModuleType("src.clients")
_ws = ModuleType("src.clients.agent_ws_client")


def _get_osm_type_prefix(osm_type: str | None) -> str | None:
    match osm_type:
        case "relation":
            return "R"
        case "way":
            return "W"
        case "node":
            return "N"
        case _:
            return None


_ws.get_osm_type_prefix = _get_osm_type_prefix  # type: ignore[attr-defined]
sys.modules.setdefault("src", _stub)
sys.modules["src.clients"] = _clients
sys.modules["src.clients.agent_ws_client"] = _ws

_MODULE_PATH = Path(__file__).resolve().parents[1] / "ui" / "location_input.py"
_SPEC = importlib.util.spec_from_file_location("location_input", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_location_input = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_location_input)
_parse_bbox = _location_input._parse_bbox
location_attachment = _location_input.location_attachment


def test_parse_bbox_nominatim_order():
    assert _parse_bbox(["48.0", "49.0", "2.0", "3.0"]) == [48.0, 49.0, 2.0, 3.0]


def test_location_attachment():
    payload = location_attachment(
        {
            "display_name": "Paris, France",
            "lat": 48.8566,
            "lon": 2.3522,
            "place_id": 1,
            "osm_id": 7444,
            "osm_type": "relation",
        }
    )
    assert payload["type"] == "location"
    assert payload["name"] == "Paris, France"
    assert payload["coordinates"] == [48.8566, 2.3522]
    assert payload["osm_type"] == "relation"
    assert payload["osm_type_prefix"] == "R"
