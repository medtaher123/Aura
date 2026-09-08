"""Unit tests for FIRMS source selection in fire detection."""

from datetime import date

import pytest

from modules.hazards.fire_detection import (
    _dedupe_fire_dataframe,
    _load_fire_dataframe,
    _needs_api,
    _needs_archive,
    should_use_api,
    should_use_archive,
)


TODAY = date(2026, 8, 19)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("start_date", "end_date", "expect_archive", "expect_api"),
    [
        ("2026-07-01", "2026-08-31", True, True),
        ("2026-08-15", "2026-08-19", False, True),
        ("2024-01-01", "2024-01-07", True, False),
        # 7-day window crosses the 5-day NRT cutoff → archive + API
        ("2026-08-12", "2026-08-19", True, True),
        ("2026-08-01", "2026-08-10", True, False),
    ],
)
def test_source_selection_for_date_ranges(
    start_date, end_date, expect_archive, expect_api
):
    start_obj = date.fromisoformat(start_date)
    end_obj = date.fromisoformat(end_date)
    assert _needs_archive(start_obj, today=TODAY) is expect_archive
    assert _needs_api(end_obj, today=TODAY) is expect_api
    assert should_use_archive(start_date, end_date) is expect_archive
    assert should_use_api(start_date, end_date) is expect_api


@pytest.mark.unit
def test_dedupe_fire_dataframe_removes_duplicate_hotspots():
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "latitude": 44.62,
                "longitude": -1.25,
                "acq_date": "2026-07-22",
                "acq_time": "1200",
                "satellite": "N20",
            },
            {
                "latitude": 44.62,
                "longitude": -1.25,
                "acq_date": "2026-07-22",
                "acq_time": "1200",
                "satellite": "N20",
            },
            {
                "latitude": 44.63,
                "longitude": -1.24,
                "acq_date": "2026-07-22",
                "acq_time": "1215",
                "satellite": "N20",
            },
        ]
    )
    deduped = _dedupe_fire_dataframe(df)
    assert len(deduped) == 2


@pytest.mark.unit
def test_load_fire_dataframe_merges_archive_and_api(monkeypatch):
    import pandas as pd

    archive_df = pd.DataFrame(
        [
            {
                "latitude": 44.62,
                "longitude": -1.25,
                "acq_date": "2026-07-22",
                "acq_time": "1200",
            }
        ]
    )
    api_df = pd.DataFrame(
        [
            {
                "latitude": 44.63,
                "longitude": -1.24,
                "acq_date": "2026-08-18",
                "acq_time": "1300",
            }
        ]
    )

    monkeypatch.setattr(
        "modules.hazards.fire_detection._load_archive_dataframe",
        lambda *_args, **_kwargs: archive_df,
    )
    monkeypatch.setattr(
        "modules.hazards.fire_detection._load_firms_nrt_dataframe",
        lambda *_args, **_kwargs: api_df,
    )

    df = _load_fire_dataframe(
        date(2026, 7, 1),
        date(2026, 8, 31),
        today=TODAY,
    )
    assert len(df) == 2
    assert set(df["acq_date"].astype(str)) == {"2026-07-22", "2026-08-18"}
