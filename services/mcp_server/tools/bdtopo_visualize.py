"""BDTOPO thematic map visualization via pg_tileserv MVT URLs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urljoin

from config import get_config
from mcp_singleton import mcp
from tools.bdtopo_common import resolve_area_context
from utils.bbox_service import LocationAmbiguousError
from utils.contracts import BDTOPOAreaInputMode, ToolArtifacts, ToolCoordinates, ToolResponse


def _view_state_for_context(context: dict) -> dict[str, float]:
    coords: ToolCoordinates = context["coords"]
    bbox = context.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
        lat_span = max(abs(max_lat - min_lat), 1e-4)
        zoom = max(9.0, min(16.0, math.log2(180.0 / lat_span) - 0.5))
        return {
            "latitude": (min_lat + max_lat) / 2.0,
            "longitude": (min_lon + max_lon) / 2.0,
            "zoom": float(zoom),
        }

    radius_m = float(context.get("radius_m") or 5000)
    if radius_m <= 1000:
        zoom = 15.0
    elif radius_m <= 3000:
        zoom = 14.0
    elif radius_m <= 8000:
        zoom = 13.0
    else:
        zoom = 12.0
    return {
        "latitude": coords.lat,
        "longitude": coords.lon,
        "zoom": zoom,
    }

DEFAULT_THEMES: tuple[str, ...] = (
    "buildings",
    "land_use_vegetation",
    "transport",
    "hydro_surface",
    "administratif",
)

ALL_THEMES: tuple[str, ...] = (
    "administratif",
    "transport",
    "regulated_areas",
    "activity_zones",
    "named_places",
    "toponymy",
    "buildings",
    "land_use_vegetation",
    "land_use_habitation",
    "hydro_line",
    "hydro_surface",
)


@dataclass(frozen=True)
class ThemeLayerSpec:
    key: str
    label: str
    """pg_tileserv layer id (schema.table)."""
    tile_layer: str
    style: str


THEME_SPECS: dict[str, ThemeLayerSpec] = {
    "administratif": ThemeLayerSpec(
        "administratif",
        "Administrative boundaries",
        "bdtopo_raw.commune",
        "bdtopo_administratif",
    ),
    "transport": ThemeLayerSpec(
        "transport",
        "Road network",
        "bdtopo_raw.troncon_de_route",
        "bdtopo_transport",
    ),
    "regulated_areas": ThemeLayerSpec(
        "regulated_areas",
        "Protected / regulated areas",
        "bdtopo_raw.parc_ou_reserve",
        "bdtopo_regulated",
    ),
    "activity_zones": ThemeLayerSpec(
        "activity_zones",
        "Activity / interest zones",
        "bdtopo_raw.zone_d_activite_ou_d_interet",
        "bdtopo_activity",
    ),
    "named_places": ThemeLayerSpec(
        "named_places",
        "Named places",
        "bdtopo_raw.lieu_dit_non_habite",
        "bdtopo_named_places",
    ),
    "toponymy": ThemeLayerSpec(
        "toponymy",
        "Toponymy",
        "bdtopo_raw.toponymie",
        "bdtopo_toponymy",
    ),
    "buildings": ThemeLayerSpec(
        "buildings",
        "Buildings",
        "bdtopo_raw.batiment",
        "bdtopo_buildings",
    ),
    "land_use_vegetation": ThemeLayerSpec(
        "land_use_vegetation",
        "Vegetation / land cover",
        "bdtopo_raw.zone_de_vegetation",
        "bdtopo_vegetation",
    ),
    "land_use_habitation": ThemeLayerSpec(
        "land_use_habitation",
        "Habitation zones",
        "bdtopo_raw.zone_d_habitation",
        "bdtopo_habitation",
    ),
    "hydro_line": ThemeLayerSpec(
        "hydro_line",
        "Hydrography (lines)",
        "bdtopo_raw.troncon_hydrographique",
        "bdtopo_hydro_line",
    ),
    "hydro_surface": ThemeLayerSpec(
        "hydro_surface",
        "Hydrography (surfaces)",
        "bdtopo_raw.surface_hydrographique",
        "bdtopo_hydro_surface",
    ),
}


def _normalize_themes(themes: list[str] | None) -> list[str]:
    if not themes:
        return list(DEFAULT_THEMES)
    selected: list[str] = []
    for raw in themes:
        key = (raw or "").strip().lower().replace(" ", "_")
        if key in THEME_SPECS and key not in selected:
            selected.append(key)
    return selected or list(DEFAULT_THEMES)


def _resolve_tile_server_url() -> str:
    return (get_config().bdtopo_tile_server_url or "").strip().rstrip("/")


def _tile_url(base_url: str, tile_layer: str) -> str:
    return urljoin(f"{base_url}/", f"{tile_layer}/{{z}}/{{x}}/{{y}}.pbf")


def _artifact_bbox(context: dict) -> list[float] | None:
    """Return bbox as [min_lat, max_lat, min_lon, max_lon] for vector-tile clients."""
    bbox = context.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
        return [min_lat, max_lat, min_lon, max_lon]

    if context.get("mode") != "point":
        return None

    coords: ToolCoordinates = context["coords"]
    radius_m = float(context.get("radius_m") or 0)
    # ~111_320 m per degree latitude; crude lon correction at center.
    lat_delta = max(radius_m, 1.0) / 111_320.0
    lon_scale = max(0.2, abs(math.cos(math.radians(coords.lat))))
    lon_delta = lat_delta / lon_scale
    return [
        coords.lat - lat_delta,
        coords.lat + lat_delta,
        coords.lon - lon_delta,
        coords.lon + lon_delta,
    ]


def _build_vector_tile_map(
    *,
    title: str,
    context: dict,
    themes: list[str],
    tile_server_url: str,
) -> dict:
    coords: ToolCoordinates = context["coords"]
    radius_m = context.get("radius_m") if context.get("mode") == "point" else None
    view_state = _view_state_for_context(context)

    vector_layers = [
        {
            "name": THEME_SPECS[key].label,
            "tile_url": _tile_url(tile_server_url, THEME_SPECS[key].tile_layer),
            "style": THEME_SPECS[key].style,
            "visible": True,
            "theme": key,
        }
        for key in themes
    ]

    map_spec: dict = {
        "renderer": "vector_tile",
        "title": title,
        "view_state": view_state,
        "vector_layers": vector_layers,
        "stats": {
            "theme_count": len(vector_layers),
            "themes": themes,
        },
    }
    artifact_bbox = _artifact_bbox(context)
    if artifact_bbox:
        map_spec["bbox"] = artifact_bbox
    if radius_m is not None:
        map_spec["query_point"] = {
            "lat": coords.lat,
            "lon": coords.lon,
            "radius_m": radius_m,
        }
    return map_spec


@mcp.tool()
def bdtopo_visualize_tool(
    input_mode: BDTOPOAreaInputMode = "point",
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int | None = None,
    place_name: str | None = None,
    bbox: list[float] | None = None,
    themes: list[str] | None = None,
) -> ToolResponse:
    """
    Visualize BDTOPO thematic layers as a vector-tile map artifact.

    Returns lightweight map parameters (view_state + pg_tileserv MVT URLs). The
    client fetches tiles directly; geometries are not embedded in the response.

    Args:
        input_mode: point, place_name, or bbox.
        lat/lon: Required for point mode.
        radius_m: Search/view radius in meters for point mode (default from config).
        place_name: Required for place_name mode.
        bbox: [min_lon, min_lat, max_lon, max_lat] for bbox mode.
        themes: Optional theme list. Defaults to buildings, vegetation, transport,
            hydro surfaces, and administrative boundaries.
    """
    tool_name = "bdtopo_visualize_tool"
    tile_server_url = _resolve_tile_server_url()
    if not tile_server_url:
        return ToolResponse(
            tool_name=tool_name,
            message=(
                "BDTOPO tile server is not configured. "
                "Set BDTOPO_TILE_SERVER_URL (e.g. http://localhost:7801)."
            ),
            error=True,
        )

    config = get_config()
    effective_radius = int(
        radius_m if radius_m is not None else config.bdtopo_default_radius_m
    )
    selected_themes = _normalize_themes(themes)

    try:
        context = resolve_area_context(
            input_mode=input_mode,
            lat=lat,
            lon=lon,
            radius_m=effective_radius,
            place_name=place_name,
            bbox=bbox,
        )
    except LocationAmbiguousError as exc:
        return ToolResponse(
            tool_name=tool_name,
            message=(
                f"I found multiple matches for '{exc.query}'. "
                "Please confirm the correct location."
            ),
            city=place_name,
            data={
                "needs_location_confirmation": True,
                "location_query": exc.query,
                "candidates": exc.candidates,
                "resume_patch": {"field": "place_name"},
            },
            error=False,
        )
    except Exception as exc:
        return ToolResponse(
            tool_name=tool_name,
            message=f"Invalid spatial input: {exc}",
            error=True,
        )

    coords: ToolCoordinates = context["coords"]
    place_label = context.get("place_label") or place_name
    title_suffix = place_label or f"{coords.lat:.4f}, {coords.lon:.4f}"
    map_spec = _build_vector_tile_map(
        title=f"BDTOPO map — {title_suffix}",
        context=context,
        themes=selected_themes,
        tile_server_url=tile_server_url,
    )

    layer_summaries = [
        {
            "theme": key,
            "label": THEME_SPECS[key].label,
            "tile_layer": THEME_SPECS[key].tile_layer,
            "tile_url": _tile_url(tile_server_url, THEME_SPECS[key].tile_layer),
            "style": THEME_SPECS[key].style,
        }
        for key in selected_themes
    ]

    return ToolResponse(
        tool_name=tool_name,
        message=(
            f"BDTOPO vector-tile map for {title_suffix} with "
            f"{len(selected_themes)} theme layer(s)."
        ),
        city=place_label,
        coordinates=coords,
        artifacts=ToolArtifacts(maps=[map_spec], thumbnails=[], urls=[]),
        data={
            "input_mode": input_mode,
            "radius_m": context["radius_m"],
            "bbox": context.get("bbox"),
            "tile_server_url": tile_server_url,
            "themes_requested": selected_themes,
            "available_themes": list(ALL_THEMES),
            "default_themes": list(DEFAULT_THEMES),
            "layers": layer_summaries,
            "prompt_hints": [
                "Toggle themes with the themes parameter (e.g. buildings, transport, hydro_surface).",
                "Tiles are loaded client-side from pg_tileserv; no GeoJSON is embedded.",
            ],
        },
        error=False,
    )
