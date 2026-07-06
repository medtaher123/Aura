"""Strategy-based artifact aggregation for graph tool responses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ...tools.contracts import ToolArtifacts
from .models import ArtifactBundle


def _dedup(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


class ArtifactMerger(ABC):
    @abstractmethod
    def can_merge(self, spec: dict[str, Any]) -> bool:
        pass

    @abstractmethod
    def merge(self, specs: list[dict[str, Any]]) -> dict[str, Any]:
        pass


class PydeckMerger(ArtifactMerger):
    """Merge Pydeck / deck.gl-style map specs by concatenating layers."""

    def can_merge(self, spec: dict[str, Any]) -> bool:
        return isinstance(spec.get("layers"), list) or isinstance(spec.get("points"), list)

    def merge(self, specs: list[dict[str, Any]]) -> dict[str, Any]:
        if not specs:
            return {}
        if len(specs) == 1:
            return dict(specs[0])

        base = dict(specs[0])
        combined_layers: list[dict] = []
        titles: list[str] = []
        tooltip = base.get("tooltip") if isinstance(base.get("tooltip"), dict) else None

        for spec in specs:
            combined_layers.extend(self._layers_from_spec(spec))
            title = spec.get("title")
            if isinstance(title, str) and title.strip():
                titles.append(title.strip())
            if tooltip is None and isinstance(spec.get("tooltip"), dict):
                tooltip = spec.get("tooltip")

        seen_titles: set[str] = set()
        titles = [t for t in titles if not (t in seen_titles or seen_titles.add(t))]
        if titles:
            base["title"] = " + ".join(titles)
        if tooltip is not None:
            base["tooltip"] = tooltip

        for key in (
            "points",
            "fill_color",
            "radius",
            "radius_units",
            "radius_min_pixels",
            "radius_max_pixels",
            "get_position",
        ):
            base.pop(key, None)
        base["layers"] = combined_layers
        return base

    @staticmethod
    def _layers_from_spec(spec: dict[str, Any]) -> list[dict]:
        layers: list[dict] = []
        layer_specs = spec.get("layers")
        if isinstance(layer_specs, list):
            layers.extend([x for x in layer_specs if isinstance(x, dict)])
        points = spec.get("points")
        if isinstance(points, list):
            layers.append(
                {
                    "type": "ScatterplotLayer",
                    "data": points,
                    "get_position": spec.get("get_position", "[lon, lat]"),
                    "get_radius": spec.get("radius", 50),
                    "radius_units": spec.get("radius_units", "meters"),
                    "radius_min_pixels": spec.get("radius_min_pixels", 3),
                    "radius_max_pixels": spec.get("radius_max_pixels", 15),
                    "get_fill_color": spec.get("fill_color", [255, 0, 0, 160]),
                    "pickable": bool(spec.get("pickable", True)),
                }
            )
        return layers


class ArtifactAggregator:
    """Route map specs to merger strategies and assemble ToolArtifacts."""

    def __init__(self, mergers: list[ArtifactMerger] | None = None):
        self.mergers = mergers or [PydeckMerger()]

    def aggregate(
        self,
        bundles: list[ArtifactBundle],
        extra_urls: list[str] | None = None,
    ) -> ToolArtifacts:
        maps_str: list[str] = []
        maps_other: list[Any] = []
        thumbs: list[str] = []
        urls: list[str] = []

        for bundle in bundles:
            for item in bundle.maps:
                if isinstance(item, str):
                    maps_str.append(item)
                elif isinstance(item, dict):
                    maps_other.append(item)
            thumbs.extend(bundle.thumbnails)
            urls.extend(bundle.urls)

        urls.extend(u for u in (extra_urls or []) if u.strip())

        maps_str = _dedup(maps_str)
        thumbs = _dedup(thumbs)
        urls = _dedup(urls)

        routed: dict[ArtifactMerger, list[dict[str, Any]]] = {}
        non_routed: list[Any] = []

        for spec in maps_other:
            if not isinstance(spec, dict):
                non_routed.append(spec)
                continue
            merger = self._merger_for(spec)
            if merger is None:
                non_routed.append(spec)
            else:
                routed.setdefault(merger, []).append(spec)

        combined_specs: list[Any] = []
        for merger, specs in routed.items():
            combined_specs.append(merger.merge(specs))

        combined_specs.extend(non_routed)
        merged_maps: list[Any] = [*maps_str, *combined_specs]
        return ToolArtifacts(maps=merged_maps, thumbnails=thumbs, urls=urls)

    def _merger_for(self, spec: dict[str, Any]) -> ArtifactMerger | None:
        for merger in self.mergers:
            if merger.can_merge(spec):
                return merger
        return None
