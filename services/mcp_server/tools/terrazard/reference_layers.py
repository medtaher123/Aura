"""Reference overlay catalog for TerraZard map artifacts.

Reference layers are external context overlays (e.g. Esri land cover) and are
separate from TerraZard hazard MVT layers served via pg_tileserv.
"""

from __future__ import annotations

from dataclasses import dataclass

REFERENCE_TYPE_ESRI_LAND_COVER = "esri_land_cover"
PRESET_PERMANENT_WATER = "permanent_water"


@dataclass(frozen=True)
class ReferenceLayerConfig:
    type: str
    preset: str
    name: str
    visible: bool = True


@dataclass(frozen=True)
class EsriLandCoverPreset:
    default_name: str
    default_visible: bool = True


ESRI_LAND_COVER_PRESETS: dict[str, EsriLandCoverPreset] = {
    PRESET_PERMANENT_WATER: EsriLandCoverPreset(
        default_name="Permanent Water",
        default_visible=True,
    ),
}


def build_reference_layer(preset: str) -> ReferenceLayerConfig:
    if preset not in ESRI_LAND_COVER_PRESETS:
        raise ValueError(f"Unknown reference layer preset: {preset}")

    spec = ESRI_LAND_COVER_PRESETS[preset]
    return ReferenceLayerConfig(
        type=REFERENCE_TYPE_ESRI_LAND_COVER,
        preset=preset,
        name=spec.default_name,
        visible=spec.default_visible,
    )


def default_terrazard_reference_layers() -> list[ReferenceLayerConfig]:
    """Default reference overlays attached to TerraZard vector-tile maps."""
    return [build_reference_layer(PRESET_PERMANENT_WATER)]
