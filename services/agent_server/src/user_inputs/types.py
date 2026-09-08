"""Shared type aliases and helpers for user-input kinds."""

from __future__ import annotations

from typing import Literal, Optional

InputKind = Literal["location", "bounding_box", "multiple_choice"]

OTHER_OPTION_ID = "__other__"

OSMType = Literal["relation", "way", "node"]
OSMPrefixType = Literal["R", "W", "N"]


def get_osm_type_prefix(osm_type: str | None) -> Optional[OSMPrefixType]:
    match osm_type:
        case "relation":
            return "R"
        case "way":
            return "W"
        case "node":
            return "N"
        case _:
            return None
