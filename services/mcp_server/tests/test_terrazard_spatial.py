"""Unit tests for TerraZard date normalization."""

from __future__ import annotations

import pytest

from tools.terrazard.errors import TerrazardDataError
from tools.terrazard.spatial import (
    normalize_terrazard_date,
    validate_dates,
    validate_observation_date,
)


@pytest.mark.unit
def test_normalize_terrazard_date_compact():
    assert normalize_terrazard_date("20240315") == "20240315"


@pytest.mark.unit
def test_normalize_terrazard_date_iso():
    assert normalize_terrazard_date("2024-03-15") == "20240315"


@pytest.mark.unit
def test_validate_observation_date_accepts_iso():
    assert validate_observation_date("2024-03-15") == "20240315"


@pytest.mark.unit
def test_validate_dates_accepts_iso():
    start, end = validate_dates("2024-01-01", "2024-12-31")
    assert start == "20240101"
    assert end == "20241231"


@pytest.mark.unit
def test_normalize_terrazard_date_rejects_invalid():
    with pytest.raises(TerrazardDataError, match="must be YYYYMMDD or YYYY-MM-DD"):
        normalize_terrazard_date("15/03/2024", field_name="observation_date")
