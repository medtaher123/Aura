"""Unit tests for TerraZard analytics service."""

from __future__ import annotations

import pytest

from tools.terrazard.analytics_service import (
    DateSelectionPolicy,
    assess_data_quality,
    classify_severity,
    compute_temporal_context,
)
from tools.terrazard.repository import WaterDateCount


@pytest.mark.unit
def test_classify_severity_major_tier():
    result = classify_severity(water_count=400, regional_peak_water_count=500)
    assert result.tier == "major"
    assert result.regional_percentile == 0.8


@pytest.mark.unit
def test_classify_severity_noise_floor():
    result = classify_severity(water_count=5, regional_peak_water_count=20)
    assert result.tier == "noise"


@pytest.mark.unit
def test_date_selection_prefers_low_cloud_high_water():
    dates = [
        WaterDateCount("20240101", water_count=10, cloud_count=20),
        WaterDateCount("20240102", water_count=40, cloud_count=2),
        WaterDateCount("20240103", water_count=50, cloud_count=30),
    ]
    selection = DateSelectionPolicy.pick_recommended_date(dates)
    assert selection.date == "20240102"


@pytest.mark.unit
def test_date_selection_honors_explicit_date():
    dates = [
        WaterDateCount("20240101", water_count=10, cloud_count=1),
        WaterDateCount("20240102", water_count=40, cloud_count=1),
    ]
    selection = DateSelectionPolicy.pick_recommended_date(
        dates, observation_date="20240101"
    )
    assert selection.date == "20240101"
    assert "User-specified" in selection.reason


@pytest.mark.unit
def test_compute_temporal_context_exceptional():
    dates = [
        WaterDateCount("20240101", water_count=10, cloud_count=0),
        WaterDateCount("20240102", water_count=12, cloud_count=0),
        WaterDateCount("20240103", water_count=30, cloud_count=0),
    ]
    temporal = compute_temporal_context(30, dates)
    assert temporal.anomaly == "exceptional"


@pytest.mark.unit
def test_assess_data_quality_flags_cloudy_dates():
    dates = [
        WaterDateCount("20240101", water_count=10, cloud_count=30),
        WaterDateCount("20240102", water_count=20, cloud_count=1),
    ]
    quality = assess_data_quality(10, 30, dates, "20240101")
    assert quality.usable_for_analysis is False
    assert "20240102" in quality.alternate_dates
