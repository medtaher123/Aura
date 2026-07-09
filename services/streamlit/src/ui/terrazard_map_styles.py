"""Folium vector-tile style presets for TerraZard hazard maps."""

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

STYLE_REGISTRY = {
    "water_depth": WATER_DEPTH_STYLE,
    "cloud": CLOUD_STYLE,
}


def get_style_options(style_key: str) -> dict:
    """Return Folium VectorGridProtobuf options for a named style preset."""
    return STYLE_REGISTRY.get(style_key, CLOUD_STYLE)
