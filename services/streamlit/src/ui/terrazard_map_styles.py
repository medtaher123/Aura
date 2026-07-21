"""Folium vector-tile style presets for TerraZard and BDTOPO maps."""

from __future__ import annotations

from folium import JsCode

CLOUD_STYLE = {
    "vectorTileLayerStyles": {
        "default": {
            "fill": True,
            "fillColor": "white",
            "color": "white",
            "fillOpacity": 0.3,
            "weight": 1,
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


def _vt_styles(*layer_names: str, style: dict) -> dict:
    """Apply the same paint style under pg_tileserv table names and 'default'."""
    named = {name: style for name in layer_names}
    named["default"] = style
    return {"vectorTileLayerStyles": named}


def _polygon_paint(
    fill_color: str,
    *,
    fill_opacity: float = 0.45,
    stroke: str | None = None,
    weight: float = 1.0,
) -> dict:
    return {
        "fill": True,
        "fillColor": fill_color,
        "color": stroke or fill_color,
        "fillOpacity": fill_opacity,
        "weight": weight,
    }


def _line_paint(color: str, *, weight: float = 1.5) -> dict:
    return {
        "fill": False,
        "color": color,
        "weight": weight,
        "opacity": 0.9,
    }


def _point_paint(color: str, *, radius: float = 4.0) -> dict:
    return {
        "fill": True,
        "fillColor": color,
        "color": color,
        "fillOpacity": 0.85,
        "radius": radius,
        "weight": 1,
    }


STYLE_REGISTRY = {
    "water_depth": WATER_DEPTH_STYLE,
    "cloud": CLOUD_STYLE,
    "bdtopo_administratif": _vt_styles(
        "commune", style=_polygon_paint("#757575", fill_opacity=0.15, weight=1.5)
    ),
    "bdtopo_transport": _vt_styles(
        "troncon_de_route", style=_line_paint("#424242", weight=1.25)
    ),
    "bdtopo_regulated": _vt_styles(
        "parc_ou_reserve", style=_polygon_paint("#FF9800", fill_opacity=0.35)
    ),
    "bdtopo_activity": _vt_styles(
        "zone_d_activite_ou_d_interet",
        style=_polygon_paint("#FFEB3B", fill_opacity=0.35, stroke="#FBC02D"),
    ),
    "bdtopo_named_places": _vt_styles(
        "lieu_dit_non_habite", style=_point_paint("#9C27B0")
    ),
    "bdtopo_toponymy": _vt_styles("toponymie", style=_point_paint("#673AB7")),
    "bdtopo_buildings": _vt_styles(
        "batiment", style=_polygon_paint("#E91E63", fill_opacity=0.5)
    ),
    "bdtopo_vegetation": _vt_styles(
        "zone_de_vegetation", style=_polygon_paint("#4CAF50", fill_opacity=0.4)
    ),
    "bdtopo_habitation": _vt_styles(
        "zone_d_habitation", style=_polygon_paint("#FF5722", fill_opacity=0.35)
    ),
    "bdtopo_hydro_line": _vt_styles(
        "troncon_hydrographique", style=_line_paint("#03A9F4", weight=1.5)
    ),
    "bdtopo_hydro_surface": _vt_styles(
        "surface_hydrographique", style=_polygon_paint("#03A9F4", fill_opacity=0.45)
    ),
}


def get_style_options(style_key: str) -> dict:
    """Return Folium VectorGridProtobuf options for a named style preset."""
    return STYLE_REGISTRY.get(style_key, CLOUD_STYLE)
