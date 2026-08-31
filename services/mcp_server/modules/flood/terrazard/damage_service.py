"""Estimate flood damage from TerraZard depth rasters and BDTOPO footprints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from modules.geospatial.bdtopo_common import resolve_database_url
from modules.flood.flood_depth_damage import _resolve_year, compute_unit_damage_eur
from modules.flood.terrazard.bdtopo_exposure import (
    ExposureSlice,
    collect_bdtopo_exposure,
    fetch_bdtopo_features,
)
from modules.flood.terrazard.depth_bands import DepthBand, fetch_hazard_depth_polygons
from modules.flood.terrazard.depth_raster import build_depth_raster
from modules.flood.terrazard.errors import TerrazardDataError
from modules.flood.terrazard.repository import HazardMaskRepository
from modules.flood.terrazard.spatial import format_terrazard_date
from modules.flood.terrazard.tile_url_builder import HazardLayerTileBuilder

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
    touched_buildings: dict[str, Any]

class FloodDamageService:
    """Combine TerraZard depth raster, BDTOPO zonal exposure, and damage curves."""

    def __init__(self, repository: HazardMaskRepository | None = None) -> None:
        self._repository = repository or HazardMaskRepository()

    def estimate(
        self,
        *,
        observation_date: date,
        bbox: list[float],
        location_name: str,
        #model_id: str | None = None,
        country: str = "France",
        #year: int | None = None,
        continent: str = "Europe",
    ) -> FloodDamageEstimate:
        #resolved_model = HazardLayerTileBuilder.validate_model_id(
        #    model_id or "flood80"
        #)
        resolved_model = "flood80"
        if not resolve_database_url():
            raise TerrazardDataError(
                "BDTOPO database is not configured. Set BDTOPO_DATABASE_URL."
            )

        date_key = format_terrazard_date(observation_date)
        map_stats = self._repository.get_map_stats(
            date_key, resolved_model, bbox
        )
        if map_stats.water_count <= 0:
            raise TerrazardDataError(
                f"No TerraZard flood polygons found for {location_name} on {date_key}."
            )

        hazard_polygons = fetch_hazard_depth_polygons(
            observation_date=date_key,
            model_id=resolved_model,
            bbox=bbox,
        )
        if not hazard_polygons:
            raise TerrazardDataError(
                "Could not load TerraZard hazard polygons for depth rasterization."
            )

        depth_raster = build_depth_raster(hazard_polygons, bbox)
        depth_bands = depth_raster.depth_bands
        if not depth_bands:
            raise TerrazardDataError(
                "Could not derive exclusive depth bands from TerraZard polygons."
            )

        flood_bbox = depth_raster.flood_bbox_wgs84()
        bdtopo_features = fetch_bdtopo_features(bbox, flood_bbox=flood_bbox)
        zonal = collect_bdtopo_exposure(depth_raster, bdtopo_features)
        exposure_slices = zonal.exposure_slices

        resolved_year = observation_date.year
        breakdown_rows = self._damage_breakdown(
            exposure_slices,
            country=country,
            year=resolved_year,
            continent=continent,
        )
        touched_buildings = self._annotate_touched_building_damage(
            zonal.touched_buildings,
            country=country,
            year=resolved_year,
            continent=continent,
        )

        total_damage = sum(row.total_damage_eur for row in breakdown_rows)
        total_exposed_area = sum(row.area_m2 for row in breakdown_rows)
        total_flooded_area = depth_raster.total_flooded_area_m2
        building_count = sum(
            row.feature_count
            for row in breakdown_rows
            if row.source == "bdtopo_raw.batiment"
        )

        by_asset = self._aggregate_by_asset(breakdown_rows)
        by_depth = self._aggregate_by_depth(breakdown_rows, depth_bands)

        caveats = [
            "Permanent water excluded from TerraZard flood polygons",
            (
                f"Flood extent is rasterized at ~{depth_raster.resolution_m:.1f} m "
                f"with a {depth_raster.flood_buffer_m:.0f} m buffer "
                "(TerraZard boundaries are approximate)"
            ),
            "Exposed areas are approximate (pixel-weighted footprint overlap)",
            "Damage uses JRC global depth-damage curves with BDTOPO building usage and vegetation",
            "Vegetation exposure is limited to mapped agricultural land-cover classes",
            (
                "touched_buildings lists simplified footprints of buildings "
                "intersecting flood bands with per-building damage_eur (capped)"
            ),
        ]
        if total_exposed_area < total_flooded_area * 0.05:
            caveats.append(
                "Low BDTOPO overlap with flooded area; damage may be underestimated"
            )

        message = (
            f"Estimated TerraZard flood damage for {location_name} on {date_key}: "
            f"€{total_damage:,.0f} across {total_exposed_area:,.0f} m² of exposed BDTOPO "
            f"footprint ({building_count} buildings) in {len(depth_bands)} depth bands."
        )

        return FloodDamageEstimate(
            observation_date=date_key,
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
            touched_buildings=touched_buildings,
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

    @classmethod
    def _building_damage_eur(
        cls,
        *,
        asset_class: str,
        band_exposures: list[dict[str, Any]],
        country: str,
        year: int | None,
        continent: str,
    ) -> float:
        """Sum JRC damage over each depth-band area on one building footprint."""
        total = 0.0
        for exposure in band_exposures:
            try:
                area_m2 = float(exposure.get("area_m2") or 0.0)
                depth_m = float(exposure.get("representative_depth_m") or 0.0)
            except (TypeError, ValueError):
                continue
            if area_m2 <= 0:
                continue
            unit = compute_unit_damage_eur(
                country=country,
                depth_m=depth_m,
                asset_class=asset_class,
                continent=continent,
                year=year,
            )
            unit_damage = float(unit["estimated_damage"])
            if unit["unit"] == "EUR/ha":
                total += unit_damage * (area_m2 / 10_000.0)
            else:
                total += unit_damage * area_m2
        return round(total, 2)

    @classmethod
    def _annotate_touched_building_damage(
        cls,
        touched_buildings: dict[str, Any],
        *,
        country: str,
        year: int | None,
        continent: str,
    ) -> dict[str, Any]:
        """Attach ``damage_eur`` to each touched-building feature and sort by cost."""
        if not isinstance(touched_buildings, dict):
            return {"type": "FeatureCollection", "features": []}
        features = touched_buildings.get("features")
        if not isinstance(features, list):
            return {"type": "FeatureCollection", "features": []}

        annotated: list[dict[str, Any]] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties")
            if not isinstance(props, dict):
                props = {}
            else:
                props = dict(props)

            band_exposures = props.get("band_exposures")
            if not isinstance(band_exposures, list) or not band_exposures:
                # Fallback: single band from summary properties.
                try:
                    area_m2 = float(props.get("intersection_area_m2") or 0.0)
                    depth_m = float(props.get("representative_depth_m") or 0.0)
                except (TypeError, ValueError):
                    area_m2, depth_m = 0.0, 0.0
                band_exposures = (
                    [
                        {
                            "representative_depth_m": depth_m,
                            "area_m2": area_m2,
                        }
                    ]
                    if area_m2 > 0
                    else []
                )

            asset_class = str(props.get("asset_class") or "residential")
            try:
                damage_eur = cls._building_damage_eur(
                    asset_class=asset_class,
                    band_exposures=band_exposures,
                    country=country,
                    year=year,
                    continent=continent,
                )
            except Exception:
                damage_eur = 0.0

            props["damage_eur"] = damage_eur
            annotated.append({**feature, "properties": props})

        annotated.sort(
            key=lambda item: float((item.get("properties") or {}).get("damage_eur") or 0.0),
            reverse=True,
        )
        return {"type": "FeatureCollection", "features": annotated}

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
