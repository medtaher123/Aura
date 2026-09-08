"""Build pg_tileserv MVT tile URLs for TerraZard hazard layers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urljoin

from config import get_config
from modules.flood.terrazard.errors import TerrazardDataError
from modules.flood.terrazard.repository import MapStats
from modules.flood.terrazard import styles

ALLOWED_MODEL_IDS = frozenset({"flood80"})

HAZARD_LAYER_PATH = "public.get_hazard_layer/{z}/{x}/{y}.pbf"

@dataclass(frozen=True)
class VectorLayerConfig:
    name: str
    tile_url: str
    style: str
    visible: bool = True

class TileUrlBuilder(ABC):
    """Protocol for building vector tile layer configurations."""

    @abstractmethod
    def build_layers(
        self, observation_date: str, model_id: str, stats: MapStats
    ) -> list[VectorLayerConfig]:
        raise NotImplementedError

class HazardLayerTileBuilder(TileUrlBuilder):
    """Build single-date hazard layer tile URLs."""

    def __init__(self, tile_server_url: str | None = None) -> None:
        if tile_server_url is not None:
            self._tile_server_url = tile_server_url.rstrip("/")
        else:
            self._tile_server_url = get_config().terrazard_tile_server_url.rstrip("/")

    @staticmethod
    def validate_model_id(model_id: str) -> str:
        normalized = model_id.strip()
        if normalized not in ALLOWED_MODEL_IDS:
            allowed = ", ".join(sorted(ALLOWED_MODEL_IDS))
            raise TerrazardDataError(
                f"Unsupported model_id '{model_id}'. Allowed values: {allowed}."
            )
        return normalized

    def _build_layer_url(self, observation_date: str, model_id: str, hazard_class: int) -> str:
        if not self._tile_server_url:
            raise TerrazardDataError(
                "TerraZard tile server is not configured. Set TERRAZARD_TILE_SERVER_URL."
            )

        base = urljoin(f"{self._tile_server_url}/", HAZARD_LAYER_PATH)
        return (
            f"{base}?p_date={observation_date}"
            f"&p_class={hazard_class}"
            f"&p_model={model_id}"
        )

    def build_layers(
        self,
        observation_date: str,
        model_id: str,
        stats: MapStats,
    ) -> list[VectorLayerConfig]:
        validated_model = self.validate_model_id(model_id)
        layers: list[VectorLayerConfig] = []

        if stats.water_count > 0:
            layers.append(
                VectorLayerConfig(
                    name="Water Depth",
                    tile_url=self._build_layer_url(observation_date, validated_model, 1),
                    style=styles.WATER_DEPTH,
                    visible=True,
                )
            )

        if stats.cloud_count > 0:
            layers.append(
                VectorLayerConfig(
                    name="Clouds",
                    tile_url=self._build_layer_url(observation_date, validated_model, -1),
                    style=styles.CLOUD,
                    visible=True,
                )
            )

        return layers
