"""Smoke-test the BDTOPO PostGIS database connection."""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from config import get_config

def test_connection() -> bool:
    database_url = get_config().bdtopo_database_url
    if not database_url:
        print("BDTOPO database is not configured. Set BDTOPO_DATABASE_URL.")
        return False
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                row = cursor.fetchone()
                return bool(row and row.get("ok") == 1)
    except Exception as exc:
        print(f"BDTOPO connection failed: {exc}")
        return False

if __name__ == "__main__":
    print(get_config().bdtopo_database_url)
    print(test_connection())
