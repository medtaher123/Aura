"""Compose TerraZard flood briefings for agent consumption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import get_config
from tools.terrazard.analytics_service import (
    DateSelectionPolicy,
    assess_data_quality,
    classify_severity,
    compute_temporal_context,
)
from tools.terrazard.errors import TerrazardDataError
from tools.terrazard.map_artifact_builder import build_vector_tile_map_artifact
from tools.terrazard.map_service import TerrazardMapService
from tools.terrazard.repository import DepthProfile, HazardMaskRepository
from tools.terrazard.tile_url_builder import HazardLayerTileBuilder
from utils.contracts import ToolArtifacts, ToolCoordinates


def _iso_date(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"


def _km2(area_m2: float) -> float:
    return round(area_m2 / 1_000_000, 2)


@dataclass(frozen=True)
class FloodBriefing:
    agent_briefing: dict[str, Any]
    message: str
    recommended_date: str
    available_dates: list[dict[str, Any]]
    artifacts: ToolArtifacts


class BriefingService:
    """Build composite flood briefings from repository analytics."""

    def __init__(
        self,
        repository: HazardMaskRepository | None = None,
        map_service: TerrazardMapService | None = None,
    ) -> None:
        self._repository = repository or HazardMaskRepository()
        self._map_service = map_service or TerrazardMapService(
            repository=self._repository,
            tile_builder=HazardLayerTileBuilder(),
        )

    def build(
        self,
        *,
        start_date: str,
        end_date: str,
        bbox: list[float],
        coords: ToolCoordinates,
        location_name: str,
        observation_date: str | None = None,
        model_id: str | None = None,
        include_map: bool = True,
    ) -> FloodBriefing:
        resolved_model = HazardLayerTileBuilder.validate_model_id(
            model_id or get_config().terrazard_default_model
        )

        water_dates = self._repository.get_water_date_counts(bbox, start_date, end_date)
        if not water_dates:
            raise TerrazardDataError(
                f"No flood observation dates found for {location_name} "
                f"between {start_date} and {end_date}."
            )

        try:
            selection = DateSelectionPolicy.pick_recommended_date(
                water_dates, observation_date=observation_date
            )
        except ValueError as exc:
            raise TerrazardDataError(str(exc)) from exc

        selected_date = selection.date
        map_stats = self._repository.get_map_stats(selected_date, resolved_model, bbox)
        depth_profile = self._repository.get_depth_profile(
            selected_date, resolved_model, bbox
        )
        area_stats = self._repository.get_area_stats(selected_date, resolved_model, bbox)

        regional_peak = max(entry.water_count for entry in water_dates)
        severity = classify_severity(map_stats.water_count, regional_peak)
        temporal = compute_temporal_context(map_stats.water_count, water_dates)
        data_quality = assess_data_quality(
            map_stats.water_count,
            map_stats.cloud_count,
            water_dates,
            selected_date,
        )

        caveats = [
            "Permanent water excluded from flood statistics",
            f"Observations are model {resolved_model} detections, not ground truth",
        ]
        if depth_profile is None:
            caveats.append("Depth profile unavailable for this date/area")

        depth_payload = self._depth_payload(depth_profile)
        extent_payload = {
            "flooded_km2": _km2(area_stats.water_area_m2),
            "cloud_km2": _km2(area_stats.cloud_area_m2),
        }

        follow_ups = [
            "Compare with geoserver_risk_mask_tool predicted risk",
        ]
        if depth_profile and depth_profile.median_depth_m is not None:
            follow_ups.append(
                f"Run flood_damage_city_tool at median depth {depth_profile.median_depth_m:.1f}m"
            )

        iso_selected = _iso_date(selected_date)
        agent_briefing: dict[str, Any] = {
            "headline": (
                f"{severity.label.split('(')[0].strip()} for {location_name} "
                f"on {iso_selected}"
            ),
            "recommended_date": selected_date,
            "date_selection_reason": selection.reason,
            "severity": {
                "tier": severity.tier,
                "label": severity.label,
                "water_count": severity.water_count,
                "regional_percentile": severity.regional_percentile,
                "regional_peak_water_count": severity.regional_peak_water_count,
            },
            "depth_profile": depth_payload,
            "extent": extent_payload,
            "temporal": {
                "days_with_flood_data": temporal.days_with_flood_data,
                "range_median_water_count": temporal.range_median_water_count,
                "anomaly": temporal.anomaly,
            },
            "data_quality": {
                "cloud_polygon_ratio": data_quality.cloud_polygon_ratio,
                "usable_for_analysis": data_quality.usable_for_analysis,
                "alternate_dates": data_quality.alternate_dates,
            },
            "caveats": caveats,
            "suggested_follow_ups": follow_ups,
        }

        message = self._build_message(
            location_name=location_name,
            iso_selected=iso_selected,
            severity=severity,
            extent=extent_payload,
            depth_profile=depth_profile,
            temporal=temporal,
            data_quality=data_quality,
        )

        artifacts = ToolArtifacts()
        if include_map and map_stats.total_polygons > 0:
            map_config = self._map_service.build_single_date_map(
                observation_date=selected_date,
                model_id=resolved_model,
                bbox=bbox,
                coords=coords,
                location_name=location_name,
            )
            artifacts = build_vector_tile_map_artifact(map_config)

        available_dates = [
            {
                "date": entry.date,
                "water_count": entry.water_count,
                "cloud_count": entry.cloud_count,
            }
            for entry in water_dates
        ]

        return FloodBriefing(
            agent_briefing=agent_briefing,
            message=message,
            recommended_date=selected_date,
            available_dates=available_dates,
            artifacts=artifacts,
        )

    @staticmethod
    def _depth_payload(depth_profile: DepthProfile | None) -> dict[str, Any] | None:
        if depth_profile is None:
            return None
        return {
            "max_depth_m": depth_profile.max_depth_m,
            "median_depth_m": depth_profile.median_depth_m,
            "min_depth_m": depth_profile.min_depth_m,
            "avg_depth_m": depth_profile.avg_depth_m,
            "buckets": depth_profile.buckets,
        }

    @staticmethod
    def _build_message(
        *,
        location_name: str,
        iso_selected: str,
        severity: Any,
        extent: dict[str, float],
        depth_profile: DepthProfile | None,
        temporal: Any,
        data_quality: Any,
    ) -> str:
        parts = [
            (
                f"TerraZard flood briefing for {location_name} on {iso_selected}: "
                f"{severity.tier} severity ({severity.water_count} flood polygons, "
                f"{int(severity.regional_percentile * 100)}th percentile of regional events)."
            ),
            f"Flooded extent: {extent['flooded_km2']} km²; cloud coverage ratio: "
            f"{int(data_quality.cloud_polygon_ratio * 100)}%.",
        ]
        if depth_profile and depth_profile.median_depth_m is not None:
            max_depth = depth_profile.max_depth_m
            parts.append(
                f"Depth profile: median {depth_profile.median_depth_m:.1f}m"
                + (f", max {max_depth:.1f}m" if max_depth is not None else "")
                + "."
            )
        parts.append(
            f"Temporal context: {temporal.days_with_flood_data} flood days in range "
            f"(median {temporal.range_median_water_count} polygons/day, "
            f"anomaly={temporal.anomaly})."
        )
        if not data_quality.usable_for_analysis:
            parts.append(
                "Warning: high cloud interference on selected date; consider alternate dates."
            )
        return " ".join(parts)
