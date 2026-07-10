"""Unit tests for TerraZard reference layer catalog."""

from __future__ import annotations

import pytest

from tools.terrazard.reference_layers import (
    PRESET_PERMANENT_WATER,
    REFERENCE_TYPE_ESRI_LAND_COVER,
    build_reference_layer,
    default_terrazard_reference_layers,
)


@pytest.mark.unit
def test_build_reference_layer_permanent_water():
    layer = build_reference_layer(PRESET_PERMANENT_WATER)

    assert layer.type == REFERENCE_TYPE_ESRI_LAND_COVER
    assert layer.preset == PRESET_PERMANENT_WATER
    assert layer.name == "Permanent Water"
    assert layer.visible is True


@pytest.mark.unit
def test_default_terrazard_reference_layers():
    layers = default_terrazard_reference_layers()

    assert len(layers) == 1
    assert layers[0].preset == PRESET_PERMANENT_WATER


@pytest.mark.unit
def test_build_reference_layer_rejects_unknown_preset():
    with pytest.raises(ValueError, match="Unknown reference layer preset"):
        build_reference_layer("unknown")
