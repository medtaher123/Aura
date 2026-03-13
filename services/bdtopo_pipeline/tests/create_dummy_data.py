#!/usr/bin/env python3
"""Generate a small 4-part .7z test archive containing a dummy GeoPackage.

Usage:
    python tests/create_dummy_data.py [--output-dir tests/fixtures]

The resulting files can be used with ``--mode express`` and
``BDTOPO_SOURCE_URLS_FILE`` pointing at the parts.
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import struct
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _create_dummy_gpkg(path: Path) -> None:
    """Create a minimal GeoPackage with a few geometry rows."""
    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    try:
        conn.load_extension("mod_spatialite")
    except Exception:
        pass
    conn.execute("PRAGMA application_id = 0x47504B47;")  # 'GPKG'

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES
            ('WGS 84', 4326, 'EPSG', 4326,
             'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
             'WGS 84 geographic');

        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT,
            description TEXT DEFAULT '',
            last_change TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE, min_y DOUBLE,
            max_x DOUBLE, max_y DOUBLE,
            srs_id INTEGER REFERENCES gpkg_spatial_ref_sys(srs_id)
        );

        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT PRIMARY KEY,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS commune_test (
            fid INTEGER PRIMARY KEY,
            cleabs TEXT,
            nom TEXT,
            geom BLOB
        )
    """)

    conn.execute("""
        INSERT OR IGNORE INTO gpkg_contents VALUES
        ('commune_test', 'features', 'commune_test', '', strftime('%Y-%m-%dT%H:%M:%fZ','now'),
         2.0, 48.0, 3.0, 49.0, 4326)
    """)
    conn.execute("""
        INSERT OR IGNORE INTO gpkg_geometry_columns VALUES
        ('commune_test', 'geom', 'POINT', 4326, 0, 0)
    """)

    for i in range(10_000_000):
        lon = 2.0 + i * 0.05
        lat = 48.0 + i * 0.05
        wkb = _point_to_gpkg_wkb(lon, lat, 4326)
        conn.execute(
            "INSERT INTO commune_test (cleabs, nom, geom) VALUES (?, ?, ?)",
            (f"COMMUNE{i:04d}", f"TestCommune_{i}", wkb),
        )

    conn.commit()
    conn.close()


def _point_to_gpkg_wkb(lon: float, lat: float, srid: int) -> bytes:
    """Encode a point as GeoPackage binary (GP header + WKB)."""
    flags = 0x20  # envelope type 1 (xy)
    header = b"GP"
    header += struct.pack("<B", 0)  # version
    header += struct.pack("<B", flags)
    header += struct.pack("<i", srid)
    header += struct.pack("<dddd", lon, lon, lat, lat)  # envelope
    wkb = struct.pack("<Bidddd", 1, 1, lon, lat, 0.0, 0.0)[:21]
    wkb = struct.pack("<Bi", 1, 1) + struct.pack("<dd", lon, lat)
    return header + wkb


def _split_7z(gpkg_path: Path, output_dir: Path, num_parts: int = 10) -> list[Path]:
    """Compress into a multi-volume 7z archive."""
    archive_name = output_dir / "BDTOPO_TEST.7z"
    archive_size_estimate = gpkg_path.stat().st_size // 10  # 7z compresses well
    volume_size = max(archive_size_estimate // num_parts, 512)

    subprocess.run(
        [
            "7z",
            "a",
            "-t7z",
            f"-v{volume_size}b",
            str(archive_name),
            str(gpkg_path),
        ],
        check=True,
        capture_output=True,
    )

    parts = sorted(output_dir.glob("BDTOPO_TEST.7z.*"))
    return parts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dummy BDTOPO test data")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=FIXTURE_DIR,
        help="Directory for generated fixtures",
    )
    args = parser.parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    gpkg_path = output_dir / "BDT_3-5_GPKG_WGS84G_TEST.gpkg"
    _create_dummy_gpkg(gpkg_path)
    sz = gpkg_path.stat().st_size
    print(f"Created dummy GeoPackage: {gpkg_path} ({sz / 1024 / 1024} MB)")
    if sz > 1024 * 1024 * 1024 * 24:
        print("GeoPackage is more than 24GB, skipping archive creation")
        gpkg_path.unlink()
        return

    parts = _split_7z(gpkg_path, output_dir)
    print(f"Created {len(parts)} archive parts:")
    for p in parts:
        print(f"  {p.name} ({p.stat().st_size} bytes)")

    # gpkg_path.unlink()
    print(f"\nFixtures ready in {output_dir}")


if __name__ == "__main__":
    main()
