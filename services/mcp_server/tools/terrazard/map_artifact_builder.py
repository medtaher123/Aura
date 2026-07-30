"""Convert TerraZard map domain configs into ToolArtifacts."""

from __future__ import annotations

from typing import Any

from tools.terrazard.map_service import TerrazardMapConfig
from utils.contracts import ToolArtifacts, ToolCoordinates
from utils.map_view_service import view_state_from_bbox


def treated_area_box_geojson(bbox: list[float]) -> dict[str, Any]:
    """Build a GeoJSON polygon for the treated AOI bbox ``[min_lat, max_lat, min_lon, max_lon]``."""
    min_lat, max_lat, min_lon, max_lon = (float(v) for v in bbox)
    return {
        "type": "Feature",
        "properties": {
            "name": "Treated area",
            "kind": "treated_area_bbox",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [min_lon, min_lat],
                    [max_lon, min_lat],
                    [max_lon, max_lat],
                    [min_lon, max_lat],
                    [min_lon, min_lat],
                ]
            ],
        },
    }


def build_location_map_artifact(
    coords: ToolCoordinates, bbox: list[float], name: str
) -> ToolArtifacts:
    """Build a basemap-only artifact centered on a query area."""
    view_state = view_state_from_bbox(coords, padding=0.18, min_zoom=5.0, max_zoom=10.5)
    if not view_state:
        return ToolArtifacts()

    return ToolArtifacts(
        maps=[
            {
                "title": f"TerraZard Observations Area: {name}",
                "view_state": view_state,
                "bbox": list(bbox),
                "box": treated_area_box_geojson(bbox),
            }
        ]
    )


def build_vector_tile_map_artifact(config: TerrazardMapConfig) -> ToolArtifacts:
    """Build a vector-tile map artifact from a TerraZard map config."""
    return ToolArtifacts(
        maps=[
            {
                "renderer": "vector_tile",
                "title": config.title,
                "view_state": config.view_state,
                "vector_layers": [
                    {
                        "name": layer.name,
                        "tile_url": layer.tile_url,
                        "style": layer.style,
                        "visible": layer.visible,
                    }
                    for layer in config.vector_layers
                ],
                "reference_layers": [
                    {
                        "type": layer.type,
                        "preset": layer.preset,
                        "name": layer.name,
                        "visible": layer.visible,
                    }
                    for layer in config.reference_layers
                ],
                "stats": config.stats,
                "bbox": config.bbox,
                "box": treated_area_box_geojson(config.bbox),
            }
        ]
    )
