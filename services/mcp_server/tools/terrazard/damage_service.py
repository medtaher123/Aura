"""Estimate flood damage from TerraZard masks clipped with BDTOPO land use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.bdtopo_common import resolve_database_url
from tools.flood_depth_damage import _resolve_year, compute_unit_damage_eur
from tools.terrazard.bdtopo_exposure import ExposureSlice, fetch_bdtopo_features
from tools.terrazard.depth_bands import DepthBand, fetch_hazard_depth_polygons
from tools.terrazard.errors import TerrazardDataError
from tools.terrazard.raster_engine import estimate_damage_raster
from tools.terrazard.repository import HazardMaskRepository
from tools.terrazard.tile_url_builder import HazardLayerTileBuilder


@dataclass(frozen=True)
class DamageBreakdownRow:
    source: str
    land_type: str
    asset_class: str
    depth_min_m: float
    depth_max_m: float
    representative_depth_m: float
    area_m2: float
    feature_count: int
    unit_damage: float
    unit: str
    total_damage_eur: float


@dataclass(frozen=True)
class FloodDamageEstimate:
    observation_date: str
    model_id: str
    location_name: str
    country: str
    year: int
    depth_bands: list[dict[str, Any]]
    exposure_rows: list[dict[str, Any]]
    by_asset_class: list[dict[str, Any]]
    by_depth_band: list[dict[str, Any]]
    total_damage_eur: float
    total_exposed_area_m2: float
    total_flooded_area_m2: float
    building_count: int
    caveats: list[str]
    message: str


class FloodDamageService:
    """Combine TerraZard depth rasters, BDTOPO exposure, and depth-damage curves."""

    def __init__(self, repository: HazardMaskRepository | None = None) -> None:
        self._repository = repository or HazardMaskRepository()

    def estimate(
        self,
        *,
        observation_date: str,
        bbox: list[float],
        location_name: str,
        model_id: str | None = None,
        country: str = "France",
        year: int | None = None,
        continent: str = "Europe",
    ) -> FloodDamageEstimate:
        resolved_model = HazardLayerTileBuilder.validate_model_id(
            model_id or "flood80"
        )
        if not resolve_database_url():
            raise TerrazardDataError(
                "BDTOPO database is not configured. Set BDTOPO_DATABASE_URL."
            )

        map_stats = self._repository.get_map_stats(
            observation_date, resolved_model, bbox
        )
        if map_stats.water_count <= 0:
            raise TerrazardDataError(
                f"No TerraZard flood polygons found for {location_name} on {observation_date}."
            )

        hazard_polygons = fetch_hazard_depth_polygons(
            observation_date=observation_date,
            model_id=resolved_model,
            bbox=bbox,
        )
        if not hazard_polygons:
            raise TerrazardDataError(
                "Could not load TerraZard hazard polygons for depth rasterization."
            )

        bdtopo_features = fetch_bdtopo_features(bbox)
        raster_result = estimate_damage_raster(
            hazard_polygons=hazard_polygons,
            features=bdtopo_features,
            bbox=bbox,
        )
        depth_bands = raster_result.depth_bands
        if not depth_bands:
            raise TerrazardDataError(
                "Could not derive exclusive depth bands from TerraZard polygons."
            )

        resolved_year = _resolve_year(year)
        breakdown_rows = self._damage_breakdown(
            raster_result.exposure_rows,
            country=country,
            year=resolved_year,
            continent=continent,
        )

        total_damage = sum(row.total_damage_eur for row in breakdown_rows)
        total_exposed_area = sum(row.area_m2 for row in breakdown_rows)
        total_flooded_area = raster_result.total_flooded_area_m2
        building_count = raster_result.building_count

        by_asset = self._aggregate_by_asset(breakdown_rows)
        by_depth = self._aggregate_by_depth(breakdown_rows, depth_bands)

        caveats = [
            "Permanent water excluded from TerraZard flood polygons",
            (
                "Damage uses on-the-fly raster map algebra "
                f"(~{raster_result.resolution_m:.1f} m EPSG:2154 grid) "
                "over nested TerraZard depth thresholds"
            ),
            "Damage uses JRC global depth-damage curves with BDTOPO building usage and vegetation",
            "Vegetation exposure is limited to mapped agricultural land-cover classes",
        ]
        if total_exposed_area < total_flooded_area * 0.05:
            caveats.append(
                "Low BDTOPO overlap with flooded area; damage may be underestimated"
            )

        message = (
            f"Estimated TerraZard flood damage for {location_name} on {observation_date}: "
            f"€{total_damage:,.0f} across {total_exposed_area:,.0f} m² of exposed BDTOPO "
            f"footprint ({building_count} buildings) in {len(depth_bands)} depth bands."
        )

        return FloodDamageEstimate(
            observation_date=observation_date,
            model_id=resolved_model,
            location_name=location_name,
            country=country,
            year=resolved_year,
            depth_bands=[
                {
                    "depth_min_m": band.depth_min_m,
                    "depth_max_m": band.depth_max_m,
                    "representative_depth_m": band.representative_depth_m,
                    "flooded_area_m2": round(band.flooded_area_m2, 1),
                }
                for band in depth_bands
            ],
            exposure_rows=[self._row_payload(row) for row in breakdown_rows],
            by_asset_class=by_asset,
            by_depth_band=by_depth,
            total_damage_eur=round(total_damage, 2),
            total_exposed_area_m2=round(total_exposed_area, 1),
            total_flooded_area_m2=round(total_flooded_area, 1),
            building_count=building_count,
            caveats=caveats,
            message=message,
        )

    def _damage_breakdown(
        self,
        exposure_slices: list[ExposureSlice],
        *,
        country: str,
        year: int | None,
        continent: str,
    ) -> list[DamageBreakdownRow]:
        rows: list[DamageBreakdownRow] = []
        for slice_ in exposure_slices:
            unit = compute_unit_damage_eur(
                country=country,
                depth_m=slice_.representative_depth_m,
                asset_class=slice_.asset_class,
                continent=continent,
                year=year,
            )
            unit_damage = float(unit["estimated_damage"])
            if unit["unit"] == "EUR/ha":
                area_ha = slice_.area_m2 / 10_000.0
                total_damage = unit_damage * area_ha
            else:
                total_damage = unit_damage * slice_.area_m2
            rows.append(
                DamageBreakdownRow(
                    source=slice_.source,
                    land_type=slice_.land_type,
                    asset_class=slice_.asset_class,
                    depth_min_m=slice_.depth_min_m,
                    depth_max_m=slice_.depth_max_m,
                    representative_depth_m=slice_.representative_depth_m,
                    area_m2=slice_.area_m2,
                    feature_count=slice_.feature_count,
                    unit_damage=unit_damage,
                    unit=str(unit["unit"]),
                    total_damage_eur=round(total_damage, 2),
                )
            )
        return rows

    @staticmethod
    def _row_payload(row: DamageBreakdownRow) -> dict[str, Any]:
        return {
            "source": row.source,
            "land_type": row.land_type,
            "asset_class": row.asset_class,
            "depth_min_m": row.depth_min_m,
            "depth_max_m": row.depth_max_m,
            "representative_depth_m": row.representative_depth_m,
            "area_m2": round(row.area_m2, 1),
            "feature_count": row.feature_count,
            "unit_damage": round(row.unit_damage, 2),
            "unit": row.unit,
            "total_damage_eur": row.total_damage_eur,
        }

    @staticmethod
    def _aggregate_by_asset(rows: list[DamageBreakdownRow]) -> list[dict[str, Any]]:
        totals: dict[str, dict[str, float | int]] = {}
        for row in rows:
            bucket = totals.setdefault(
                row.asset_class,
                {"asset_class": row.asset_class, "area_m2": 0.0, "total_damage_eur": 0.0},
            )
            bucket["area_m2"] = float(bucket["area_m2"]) + row.area_m2
            bucket["total_damage_eur"] = float(bucket["total_damage_eur"]) + row.total_damage_eur
        return [
            {
                "asset_class": key,
                "area_m2": round(values["area_m2"], 1),
                "total_damage_eur": round(values["total_damage_eur"], 2),
            }
            for key, values in sorted(totals.items())
        ]

    @staticmethod
    def _aggregate_by_depth(
        rows: list[DamageBreakdownRow],
        depth_bands: list[DepthBand],
    ) -> list[dict[str, Any]]:
        damage_by_band: dict[tuple[float, float], float] = {}
        area_by_band: dict[tuple[float, float], float] = {}
        for row in rows:
            key = (row.depth_min_m, row.depth_max_m)
            damage_by_band[key] = damage_by_band.get(key, 0.0) + row.total_damage_eur
            area_by_band[key] = area_by_band.get(key, 0.0) + row.area_m2

        payload: list[dict[str, Any]] = []
        for band in depth_bands:
            key = (band.depth_min_m, band.depth_max_m)
            payload.append(
                {
                    "depth_min_m": band.depth_min_m,
                    "depth_max_m": band.depth_max_m,
                    "representative_depth_m": band.representative_depth_m,
                    "flooded_area_m2": round(band.flooded_area_m2, 1),
                    "exposed_area_m2": round(area_by_band.get(key, 0.0), 1),
                    "total_damage_eur": round(damage_by_band.get(key, 0.0), 2),
                }
            )
        return payload
