"""Convert TerraZard map domain configs into ToolArtifacts."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from config import get_config
from core.logger import get_logger
from tools.bdtopo_visualize import THEME_SPECS
from tools.terrazard.errors import TerrazardDataError
from tools.terrazard.map_service import TerrazardMapConfig
from tools.terrazard.reference_layers import default_terrazard_reference_layers
from tools.terrazard.repository import MapStats
from tools.terrazard.tile_url_builder import HazardLayerTileBuilder
from utils.contracts import ToolArtifacts, ToolCoordinates
from utils.map_view_service import view_state_from_bbox

logger = get_logger(__name__)

# BDTOPO themes that feed flood-damage exposure (buildings + agricultural land).
_DAMAGE_EXPOSURE_THEMES: tuple[str, ...] = ("buildings", "land_use_vegetation")


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


def _bdtopo_tile_url(base_url: str, tile_layer: str) -> str:
    return urljoin(f"{base_url}/", f"{tile_layer}/{{z}}/{{x}}/{{y}}.pbf")


def _damage_view_state(coords: ToolCoordinates, bbox: list[float]) -> dict[str, float]:
    """Center on the AOI and zoom in enough for BDTOPO building tiles (minzoom 14)."""
    theme_minzooms = [
        THEME_SPECS[key].minzoom
        for key in _DAMAGE_EXPOSURE_THEMES
        if key in THEME_SPECS
    ]
    min_theme_zoom = float(max(theme_minzooms)) if theme_minzooms else 14.0
    center = ToolCoordinates(
        lat=(float(bbox[0]) + float(bbox[1])) / 2.0,
        lon=(float(bbox[2]) + float(bbox[3])) / 2.0,
    )
    view_state = view_state_from_bbox(
        center or coords,
        padding=0.18,
        min_zoom=5.0,
        max_zoom=max(13.0, min_theme_zoom),
    )
    view_state["zoom"] = max(float(view_state["zoom"]), min_theme_zoom)
    return view_state


def build_damage_exposure_map_artifact(
    *,
    observation_date: str,
    model_id: str,
    bbox: list[float],
    coords: ToolCoordinates,
    location_name: str,
    map_stats: MapStats,
    total_damage_eur: float,
    building_count: int,
    total_exposed_area_m2: float,
    total_flooded_area_m2: float,
    touched_buildings: dict[str, Any] | None = None,
) -> ToolArtifacts:
    """Compose TerraZard hazard + BDTOPO asset tile layers for flood-damage context.

    Returns an empty ``ToolArtifacts`` when either tile server is not configured,
    so callers can still return numeric damage results.

    When ``touched_buildings`` is a FeatureCollection of flood-intersecting
    building footprints, it is attached as a light GeoJSON overlay (not tiles).
    """
    cfg = get_config()
    terrazard_tile_url = (cfg.terrazard_tile_server_url or "").strip().rstrip("/")
    bdtopo_tile_url = (cfg.bdtopo_tile_server_url or "").strip().rstrip("/")
    if not terrazard_tile_url or not bdtopo_tile_url:
        logger.info(
            "Skipping damage exposure map: tile server URL missing "
            "(terrazard=%s, bdtopo=%s)",
            bool(terrazard_tile_url),
            bool(bdtopo_tile_url),
        )
        return ToolArtifacts()

    try:
        hazard_layers = HazardLayerTileBuilder(
            tile_server_url=terrazard_tile_url
        ).build_layers(observation_date, model_id, map_stats)
    except TerrazardDataError as exc:
        logger.warning("Skipping damage exposure map (hazard tiles): %s", exc)
        return ToolArtifacts()

    if not hazard_layers:
        logger.info("Skipping damage exposure map: no hazard tile layers")
        return ToolArtifacts()

    vector_layers: list[dict[str, Any]] = [
        {
            "name": layer.name,
            "tile_url": layer.tile_url,
            "style": layer.style,
            "visible": layer.visible,
        }
        for layer in hazard_layers
    ]
    for theme_key in _DAMAGE_EXPOSURE_THEMES:
        spec = THEME_SPECS[theme_key]
        vector_layers.append(
            {
                "name": spec.label,
                "tile_url": _bdtopo_tile_url(bdtopo_tile_url, spec.tile_layer),
                "style": spec.style,
                "minzoom": spec.minzoom,
                "visible": True,
                "theme": theme_key,
            }
        )

    reference_layers = [
        {
            "type": layer.type,
            "preset": layer.preset,
            "name": layer.name,
            "visible": layer.visible,
        }
        for layer in default_terrazard_reference_layers()
    ]

    map_spec: dict[str, Any] = {
        "renderer": "vector_tile",
        "title": f"Flood damage exposure — {location_name}",
        "view_state": _damage_view_state(coords, bbox),
        "vector_layers": vector_layers,
        "reference_layers": reference_layers,
        "stats": {
            "observation_date": observation_date,
            "model_id": model_id,
            "total_damage_eur": total_damage_eur,
            "building_count": building_count,
            "total_exposed_area_m2": total_exposed_area_m2,
            "total_flooded_area_m2": total_flooded_area_m2,
            "water_count": map_stats.water_count,
            "cloud_count": map_stats.cloud_count,
        },
        "bbox": list(bbox),
        "box": treated_area_box_geojson(bbox),
    }

    if (
        isinstance(touched_buildings, dict)
        and touched_buildings.get("type") == "FeatureCollection"
        and isinstance(touched_buildings.get("features"), list)
        and touched_buildings["features"]
    ):
        map_spec["geojson_overlays"] = [
            {
                "name": "Touched buildings",
                "data": touched_buildings,
                "style": {
                    "fillColor": "#FF6D00",
                    "color": "#E65100",
                    "fillOpacity": 0.65,
                    "weight": 1.5,
                },
            }
        ]
        map_spec["stats"]["touched_building_features"] = len(
            touched_buildings["features"]
        )

    return ToolArtifacts(maps=[map_spec])
