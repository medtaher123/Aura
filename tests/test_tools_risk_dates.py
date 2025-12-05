# tests/test_tools_risk_dates.py
from tools_risk import extract_dates_from_text

def test_year_only():
    s,e = extract_dates_from_text("2025")
    assert (s,e) == ("2025-01-01","2025-12-31")

def test_month_year_fr():
    s,e = extract_dates_from_text("septembre 2025")
    assert (s,e) == ("2025-09-01","2025-09-30")

def test_month_year_en():
    s,e = extract_dates_from_text("March 2024")
    assert (s,e) == ("2024-03-01","2024-03-31")

def test_range_years():
    s,e = extract_dates_from_text("entre 2022 et 2023")
    assert (s,e) == ("2022-01-01","2023-12-31")

def test_unique_date_fr():
    s,e = extract_dates_from_text("le 7 juillet 2023")
    assert (s,e) == ("2023-07-07","2023-07-07")

def test_iso_range():
    s,e = extract_dates_from_text("2023-06-01 au 2023-06-09")
    assert (s,e) == ("2023-06-01","2023-06-09")
