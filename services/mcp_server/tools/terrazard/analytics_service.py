"""Analytics helpers for TerraZard flood briefing."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal

from tools.terrazard.repository import WaterDateCount

SeverityTier = Literal["noise", "minor", "moderate", "significant", "major", "extreme"]
AnomalyLabel = Literal["typical", "above_typical", "exceptional"]

CLOUD_RATIO_THRESHOLD = 0.30
REGIONAL_NOISE_FLOOR = 500


@dataclass(frozen=True)
class SeverityAssessment:
    tier: SeverityTier
    label: str
    water_count: int
    regional_percentile: float
    regional_peak_water_count: int


@dataclass(frozen=True)
class DateSelection:
    date: str
    reason: str
    water_count: int
    cloud_count: int


@dataclass(frozen=True)
class TemporalContext:
    days_with_flood_data: int
    range_median_water_count: float
    anomaly: AnomalyLabel


@dataclass(frozen=True)
class DataQualityAssessment:
    cloud_polygon_ratio: float
    usable_for_analysis: bool
    alternate_dates: list[str]


def classify_severity(
    water_count: int, regional_peak_water_count: int
) -> SeverityAssessment:
    effective_max = max(regional_peak_water_count, REGIONAL_NOISE_FLOOR)
    ratio = water_count / effective_max if effective_max > 0 else 0.0

    if water_count <= effective_max * 0.02:
        tier: SeverityTier = "noise"
        label = "Background noise or permanent-water signal"
    elif water_count <= effective_max * 0.10:
        tier = "minor"
        label = "Minor pooling (bottom 10% of regional events)"
    elif water_count <= effective_max * 0.30:
        tier = "moderate"
        label = "Moderate flooding (up to 30% of regional peak)"
    elif water_count <= effective_max * 0.65:
        tier = "significant"
        label = "Significant flooding (up to 65% of regional peak)"
    elif ratio < 1.0:
        tier = "major"
        label = "Major event (top 35% of regional events)"
    else:
        tier = "extreme"
        label = "Extreme event (regional peak)"

    return SeverityAssessment(
        tier=tier,
        label=label,
        water_count=water_count,
        regional_percentile=round(min(ratio, 1.0), 2),
        regional_peak_water_count=regional_peak_water_count,
    )


def compute_temporal_context(
    selected_water_count: int, water_dates: list[WaterDateCount]
) -> TemporalContext:
    counts = [entry.water_count for entry in water_dates if entry.water_count > 0]
    if not counts:
        return TemporalContext(0, 0.0, "typical")

    median_count = float(statistics.median(counts))
    if median_count <= 0:
        anomaly: AnomalyLabel = "typical"
    elif selected_water_count >= median_count * 2:
        anomaly = "exceptional"
    elif selected_water_count > median_count * 1.25:
        anomaly = "above_typical"
    else:
        anomaly = "typical"

    return TemporalContext(
        days_with_flood_data=len(counts),
        range_median_water_count=round(median_count, 1),
        anomaly=anomaly,
    )


def assess_data_quality(
    water_count: int,
    cloud_count: int,
    water_dates: list[WaterDateCount],
    selected_date: str,
) -> DataQualityAssessment:
    total = water_count + cloud_count
    cloud_ratio = round(cloud_count / total, 2) if total > 0 else 0.0
    usable = cloud_ratio < CLOUD_RATIO_THRESHOLD

    alternates: list[str] = []
    if not usable:
        ranked = sorted(
            (
                entry
                for entry in water_dates
                if entry.date != selected_date and entry.water_count > 0
            ),
            key=lambda entry: (
                entry.cloud_count / max(entry.water_count + entry.cloud_count, 1),
                -entry.water_count,
            ),
        )
        alternates = [entry.date for entry in ranked[:3]]

    return DataQualityAssessment(
        cloud_polygon_ratio=cloud_ratio,
        usable_for_analysis=usable,
        alternate_dates=alternates,
    )


class DateSelectionPolicy:
    """Pick the best observation date for briefing."""

    @staticmethod
    def pick_recommended_date(
        water_dates: list[WaterDateCount],
        *,
        observation_date: str | None = None,
    ) -> DateSelection:
        if not water_dates:
            raise ValueError("No flood observation dates available in the selected range.")

        if observation_date:
            for entry in water_dates:
                if entry.date == observation_date:
                    return DateSelection(
                        date=entry.date,
                        reason=f"User-specified observation date ({observation_date}).",
                        water_count=entry.water_count,
                        cloud_count=entry.cloud_count,
                    )
            raise ValueError(
                f"No flood data for observation date {observation_date} in this area."
            )

        def cloud_ratio(entry: WaterDateCount) -> float:
            total = entry.water_count + entry.cloud_count
            return entry.cloud_count / total if total > 0 else 0.0

        low_cloud = [entry for entry in water_dates if cloud_ratio(entry) < CLOUD_RATIO_THRESHOLD]
        candidates = low_cloud or list(water_dates)
        best = max(candidates, key=lambda entry: entry.water_count)
        ratio_pct = int(round(cloud_ratio(best) * 100))

        if low_cloud:
            reason = (
                f"Highest water extent ({best.water_count} polygons) with low cloud "
                f"interference ({ratio_pct}%)."
            )
        else:
            reason = (
                f"Highest water extent ({best.water_count} polygons); all dates have "
                f"significant cloud cover (best: {ratio_pct}%)."
            )

        return DateSelection(
            date=best.date,
            reason=reason,
            water_count=best.water_count,
            cloud_count=best.cloud_count,
        )
