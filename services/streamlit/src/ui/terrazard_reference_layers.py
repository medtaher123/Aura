"""Esri reference overlay layers for TerraZard vector-tile maps."""

from __future__ import annotations

from typing import Any, Callable

import folium
from folium.map import Layer
from jinja2 import Template

ESRI_SENTINEL2_LAND_COVER_URL = (
    "https://ic.imagery1.arcgis.com/arcgis/rest/services/"
    "Sentinel2_10m_LandCover/ImageServer"
)

ESRI_LAND_COVER_PRESETS: dict[str, dict[str, Any]] = {
    "permanent_water": {
        "name": "Permanent Water",
        "rendering_rule": (
            '{"rasterFunction": "Isolate Water Areas for Visualization and Analysis"}'
        ),
        "pane": "cyanWaterPane",
        "pane_filter": "hue-rotate(35deg) saturate(130%) brightness(150%)",
        "pane_z_index": 390,
        "opacity": 0.75,
    },
}


class EsriLandCoverLayer(Layer):
    """Folium layer that renders an Esri ImageServer land-cover rendering rule."""

    def __init__(
        self,
        *,
        name: str,
        url: str,
        rendering_rule: str,
        pane: str,
        pane_z_index: int,
        opacity: float,
        pane_filter: str | None = None,
        show: bool = True,
    ) -> None:
        super().__init__(name=name, overlay=True, control=True, show=show)
        self.url = url
        self.rendering_rule = rendering_rule
        self.pane = pane
        self.pane_z_index = pane_z_index
        self.pane_filter = pane_filter or ""
        self.opacity = opacity

        self._template = Template(
            """
            {% macro script(this, kwargs) %}
            var map = {{ this._parent.get_name() }};

            if (!map.getPane('{{ this.pane }}')) {
                map.createPane('{{ this.pane }}');
                map.getPane('{{ this.pane }}').style.zIndex = {{ this.pane_z_index }};
                {% if this.pane_filter %}
                map.getPane('{{ this.pane }}').style.filter = '{{ this.pane_filter }}';
                {% endif %}
            }

            var {{ this.get_name() }} = L.featureGroup();

            var loadEsriLayer = function() {
                L.esri.imageMapLayer({
                    url: '{{ this.url }}',
                    renderingRule: {{ this.rendering_rule }},
                    opacity: {{ this.opacity }},
                    pane: '{{ this.pane }}'
                }).addTo({{ this.get_name() }});
            };

            if (typeof L.esri === 'undefined') {
                var esriScript = document.createElement('script');
                esriScript.src = 'https://unpkg.com/esri-leaflet@3.0.12/dist/esri-leaflet.js';
                document.head.appendChild(esriScript);
                esriScript.onload = loadEsriLayer;
            } else {
                loadEsriLayer();
            }
            {% endmacro %}
            """
        )


ReferenceLayerFactory = Callable[[dict[str, Any]], Layer | None]

_REFERENCE_LAYER_FACTORIES: dict[str, ReferenceLayerFactory] = {}


def register_reference_layer_factory(layer_type: str, factory: ReferenceLayerFactory) -> None:
    _REFERENCE_LAYER_FACTORIES[layer_type] = factory


def _build_esri_land_cover_layer(spec: dict[str, Any]) -> Layer | None:
    preset_key = spec.get("preset")
    if not isinstance(preset_key, str):
        return None

    preset = ESRI_LAND_COVER_PRESETS.get(preset_key)
    if preset is None:
        return None

    name = spec.get("name")
    layer_name = name if isinstance(name, str) and name.strip() else preset["name"]
    visible = spec.get("visible") is not False

    return EsriLandCoverLayer(
        name=layer_name,
        url=ESRI_SENTINEL2_LAND_COVER_URL,
        rendering_rule=preset["rendering_rule"],
        pane=preset["pane"],
        pane_z_index=preset["pane_z_index"],
        pane_filter=preset.get("pane_filter"),
        opacity=preset["opacity"],
        show=visible,
    )


register_reference_layer_factory("esri_land_cover", _build_esri_land_cover_layer)


def add_reference_layers(folium_map: folium.Map, reference_layers: Any) -> None:
    """Attach reference overlay layers declared in a vector-tile map artifact."""
    if not isinstance(reference_layers, list):
        return

    for layer_spec in reference_layers:
        if not isinstance(layer_spec, dict):
            continue

        layer_type = layer_spec.get("type")
        if not isinstance(layer_type, str):
            continue

        factory = _REFERENCE_LAYER_FACTORIES.get(layer_type)
        if factory is None:
            continue

        layer = factory(layer_spec)
        if layer is not None:
            layer.add_to(folium_map)
