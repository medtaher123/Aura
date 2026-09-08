"""Folium vector-tile style presets for TerraZard and BDTOPO maps.

Leaflet Path ``weight`` is screen pixels. Folium only reliably injects zoom-aware
style *functions* when VectorGridProtobuf ``options`` is a JavaScript object
string (not a Python dict). BDTOPO styles therefore return JS strings and convert
a geographic stroke width (metres) to pixels from the current zoom.
"""

from __future__ import annotations

import json
from folium import JsCode

# Default geographic stroke width for BDTOPO outlines / lines.
DEFAULT_STROKE_WIDTH_M = 0.5
# Approximate latitude used when the map center is unknown (metropolitan France).
_DEFAULT_LATITUDE = 46.5

CLOUD_STYLE = {
    "vectorTileLayerStyles": {
        "default": {
            "fill": True,
            "fillColor": "white",
            "color": "white",
            "fillOpacity": 0.3,
            "weight": 0,
        }
    }
}

DEPTH_STYLE_JS = JsCode(
    """
    function(properties, zoom) {
        var min_d = properties.depth_min;
        var color = '#e0f3ff';

        if (min_d >= 0.0 && min_d < 0.25) {
            color = '#e0f3ff';
        } else if (min_d >= 0.25 && min_d < 0.5) {
            color = '#b3d9ff';
        } else if (min_d >= 0.5 && min_d < 1.0) {
            color = '#80bfff';
        } else if (min_d >= 1.0 && min_d < 1.5) {
            color = '#4da6ff';
        } else if (min_d >= 1.5 && min_d < 2.0) {
            color = '#1a8cff';
        } else if (min_d >= 2.0 && min_d < 2.5) {
            color = '#0073e6';
        } else if (min_d >= 2.5 && min_d < 3.0) {
            color = '#0059b3';
        } else if (min_d >= 3.0 && min_d < 4.0) {
            color = '#004080';
        } else if (min_d >= 4.0 && min_d < 5.0) {
            color = '#00264d';
        } else if (min_d >= 5.0) {
            color = '#000d1a';
        }

        return {
            fill: true,
            fillColor: color,
            color: color,
            fillOpacity: 1,
            weight: 0.0
        };
    }
    """
)

WATER_DEPTH_STYLE = {
    "vectorTileLayerStyles": {
        "default": DEPTH_STYLE_JS,
    }
}


def _meters_to_pixels_js(stroke_width_m: float, latitude: float) -> str:
    """JS snippet: convert geographic metres → Leaflet Path weight (pixels)."""
    return f"""
        function metersToPixels(meters, zoom) {{
            var latRad = {float(latitude)} * Math.PI / 180.0;
            var metersPerPixel = 156543.03392 * Math.cos(latRad) / Math.pow(2, zoom);
            if (metersPerPixel <= 0) return 0;
            var px = meters / metersPerPixel;
            // Avoid invisible hairlines when very zoomed in; cap runaway pixels.
            if (px < 0.05) return 0.05;
            if (px > 8) return 8;
            return px;
        }}
        var strokePx = metersToPixels({float(stroke_width_m)}, zoom);
    """


def _style_fn_polygon(
    *,
    fill_color: str,
    fill_opacity: float,
    stroke_width_m: float,
    latitude: float,
    stroke: str | None = None,
) -> str:
    stroke_color = stroke or fill_color
    return f"""function(properties, zoom) {{
        {_meters_to_pixels_js(stroke_width_m, latitude)}
        return {{
            fill: true,
            fillColor: {json.dumps(fill_color)},
            color: {json.dumps(stroke_color)},
            fillOpacity: {float(fill_opacity)},
            weight: strokePx,
            opacity: 0.85
        }};
    }}"""


def _style_fn_line(
    *,
    color: str,
    stroke_width_m: float,
    latitude: float,
) -> str:
    return f"""function(properties, zoom) {{
        {_meters_to_pixels_js(stroke_width_m, latitude)}
        return {{
            fill: false,
            color: {json.dumps(color)},
            weight: strokePx,
            opacity: 0.9
        }};
    }}"""


def _style_fn_point(*, color: str, radius_m: float, latitude: float) -> str:
    return f"""function(properties, zoom) {{
        {_meters_to_pixels_js(radius_m, latitude)}
        return {{
            fill: true,
            fillColor: {json.dumps(color)},
            color: {json.dumps(color)},
            fillOpacity: 0.85,
            radius: strokePx,
            weight: 0
        }};
    }}"""


def _vector_grid_options_js(
    layer_names: tuple[str, ...],
    style_fn: str,
    *,
    min_zoom: int | None = None,
) -> str:
    """Build VectorGridProtobuf options as a JS object string (functions work)."""
    # Quote every layer key — pg_tileserv often emits "schema.table".
    entries = [f"{json.dumps(name)}: {style_fn}" for name in layer_names]
    styles_body = ",\n            ".join(entries)
    min_zoom_line = f"minZoom: {int(min_zoom)},\n        " if min_zoom is not None else ""
    return f"""{{
        {min_zoom_line}vectorTileLayerStyles: {{
            {styles_body}
        }}
    }}"""


# pg_tileserv MVT layer id is usually schema.table; also register the bare table.
_BDTOPO_LAYER_NAMES: dict[str, tuple[str, ...]] = {
    "bdtopo_administratif": ("bdtopo_raw.commune", "commune"),
    "bdtopo_transport": ("bdtopo_raw.troncon_de_route", "troncon_de_route"),
    "bdtopo_regulated": ("bdtopo_raw.parc_ou_reserve", "parc_ou_reserve"),
    "bdtopo_activity": (
        "bdtopo_raw.zone_d_activite_ou_d_interet",
        "zone_d_activite_ou_d_interet",
    ),
    "bdtopo_named_places": ("bdtopo_raw.lieu_dit_non_habite", "lieu_dit_non_habite"),
    "bdtopo_toponymy": ("bdtopo_raw.toponymie", "toponymie"),
    "bdtopo_buildings": ("bdtopo_raw.batiment", "batiment"),
    "bdtopo_vegetation": ("bdtopo_raw.zone_de_vegetation", "zone_de_vegetation"),
    "bdtopo_habitation": ("bdtopo_raw.zone_d_habitation", "zone_d_habitation"),
    "bdtopo_hydro_line": (
        "bdtopo_raw.troncon_hydrographique",
        "troncon_hydrographique",
    ),
    "bdtopo_hydro_surface": (
        "bdtopo_raw.surface_hydrographique",
        "surface_hydrographique",
    ),
}


def _bdtopo_options(
    style_key: str,
    *,
    latitude: float,
    stroke_width_m: float,
    min_zoom: int | None,
) -> str | None:
    names = _BDTOPO_LAYER_NAMES.get(style_key)
    if not names:
        return None

    if style_key == "bdtopo_transport":
        fn = _style_fn_line(
            color="#424242", stroke_width_m=stroke_width_m, latitude=latitude
        )
    elif style_key == "bdtopo_hydro_line":
        fn = _style_fn_line(
            color="#03A9F4", stroke_width_m=stroke_width_m, latitude=latitude
        )
    elif style_key == "bdtopo_named_places":
        fn = _style_fn_point(color="#9C27B0", radius_m=2.0, latitude=latitude)
    elif style_key == "bdtopo_toponymy":
        fn = _style_fn_point(color="#673AB7", radius_m=2.0, latitude=latitude)
    elif style_key == "bdtopo_administratif":
        fn = _style_fn_polygon(
            fill_color="#757575",
            fill_opacity=0.08,
            stroke_width_m=stroke_width_m,
            latitude=latitude,
        )
    elif style_key == "bdtopo_regulated":
        fn = _style_fn_polygon(
            fill_color="#FF9800",
            fill_opacity=0.35,
            stroke_width_m=stroke_width_m,
            latitude=latitude,
        )
    elif style_key == "bdtopo_activity":
        fn = _style_fn_polygon(
            fill_color="#FFEB3B",
            fill_opacity=0.35,
            stroke="#FBC02D",
            stroke_width_m=stroke_width_m,
            latitude=latitude,
        )
    elif style_key == "bdtopo_buildings":
        fn = _style_fn_polygon(
            fill_color="#EE5488",
            fill_opacity=0.55,
            stroke_width_m=stroke_width_m,
            latitude=latitude,
        )
    elif style_key == "bdtopo_vegetation":
        fn = _style_fn_polygon(
            fill_color="#4CAF50",
            fill_opacity=0.35,
            stroke_width_m=stroke_width_m,
            latitude=latitude,
        )
    elif style_key == "bdtopo_habitation":
        fn = _style_fn_polygon(
            fill_color="#FF5722",
            fill_opacity=0.35,
            stroke_width_m=stroke_width_m,
            latitude=latitude,
        )
    elif style_key == "bdtopo_hydro_surface":
        fn = _style_fn_polygon(
            fill_color="#03A9F4",
            fill_opacity=0.4,
            stroke_width_m=stroke_width_m,
            latitude=latitude,
        )
    else:
        return None

    return _vector_grid_options_js(names, fn, min_zoom=min_zoom)


def get_style_options(
    style_key: str,
    *,
    latitude: float = _DEFAULT_LATITUDE,
    stroke_width_m: float = DEFAULT_STROKE_WIDTH_M,
    min_zoom: int | None = None,
) -> dict | str:
    """Return Folium VectorGridProtobuf options for a named style preset.

    BDTOPO presets return a **JavaScript object string** so zoom-aware metre→pixel
    stroke functions are preserved. TerraZard presets remain Python dicts.
    """
    if style_key == "water_depth":
        return WATER_DEPTH_STYLE
    if style_key == "cloud":
        return CLOUD_STYLE

    bdtopo = _bdtopo_options(
        style_key,
        latitude=latitude,
        stroke_width_m=stroke_width_m,
        min_zoom=min_zoom,
    )
    if bdtopo is not None:
        return bdtopo

    return CLOUD_STYLE
