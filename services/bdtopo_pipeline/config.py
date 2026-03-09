"""Configuration helpers for the BDTOPO ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(slots=True)
class PipelineConfig:
    mode: str
    edition_date: str
    work_dir: Path
    download_dir: Path
    extract_dir: Path
    report_dir: Path
    postgis_dsn: str
    source_template: str
    source_urls_inline: str
    source_urls_file: str
    full_france_part_count: int
    keep_downloads: bool
    keep_extracted: bool
    download_timeout_seconds: int
    download_max_retries: int
    download_chunk_size: int
    quality_invalid_ratio_threshold: float


def _bool_env(var_name: str, default: bool) -> bool:
    raw = os.getenv(var_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(mode: str, edition_date: str) -> PipelineConfig:
    work_dir = Path(os.getenv("BDTOPO_WORK_DIR", "/tmp/bdtopo")).resolve()
    return PipelineConfig(
        mode=mode,
        edition_date=edition_date,
        work_dir=work_dir,
        download_dir=work_dir / "downloads" / edition_date,
        extract_dir=work_dir / "extracted" / edition_date,
        report_dir=work_dir / "reports" / edition_date,
        postgis_dsn=os.getenv("BDTOPO_DATABASE_URL", "").strip(),
        source_template=os.getenv(
            "BDTOPO_SOURCE_TEMPLATE",
            (
                "https://data.geopf.fr/telechargement/download/BDTOPO/"
                "BDTOPO_3-5_TOUSTHEMES_GPKG_WGS84G_FRA_{edition_date}/"
                "BDTOPO_3-5_TOUSTHEMES_GPKG_WGS84G_FRA_{edition_date}.7z.{part}"
            ),
        ).strip(),
        source_urls_inline=os.getenv("BDTOPO_SOURCE_URLS", "").strip(),
        source_urls_file=os.getenv("BDTOPO_SOURCE_URLS_FILE", "").strip(),
        full_france_part_count=int(os.getenv("BDTOPO_PART_COUNT", "9")),
        keep_downloads=_bool_env("BDTOPO_KEEP_DOWNLOADS", True),
        keep_extracted=_bool_env("BDTOPO_KEEP_EXTRACTED", True),
        download_timeout_seconds=int(os.getenv("BDTOPO_DOWNLOAD_TIMEOUT_SECONDS", "90")),
        download_max_retries=int(os.getenv("BDTOPO_DOWNLOAD_MAX_RETRIES", "5")),
        download_chunk_size=int(os.getenv("BDTOPO_DOWNLOAD_CHUNK_SIZE", "1048576")),
        quality_invalid_ratio_threshold=float(
            os.getenv("BDTOPO_QUALITY_INVALID_RATIO_THRESHOLD", "0.01")
        ),
    )

