"""Orchestrate end-to-end BDTOPO ingestion to PostGIS."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import shutil

from .config import PipelineConfig
from .downloader import download_archives
from .extractor import extract_archives
from .loader import load_gpkg_files
from .manifest import build_manifest
from .optimizer import optimize_postgis
from .quality import run_quality_checks
from .logger import get_logger

logger = get_logger("pipeline")


def run_pipeline(config: PipelineConfig) -> dict:
    urls = build_manifest(config)
    logger.info(f"Downloading {len(urls)} archives")
    archives = download_archives(config, urls)
    logger.info(f"Extracting {len(archives)} archives")
    gpkg_files = extract_archives(
        archives, config.extract_dir, timeout_seconds=config.extraction_timeout_seconds
    )
    logger.info(f"Loading {len(gpkg_files)} GPKG files")
    load_results = load_gpkg_files(config, gpkg_files)
    logger.info("Optimizing PostGIS")
    optimization = optimize_postgis(config)
    logger.info("Running quality checks")
    quality = run_quality_checks(config)

    summary = {
        "mode": config.mode,
        "edition_date": config.edition_date,
        "downloaded_files": [str(path) for path in archives],
        "extracted_gpkg_files": [str(path) for path in gpkg_files],
        "loaded_layers": [asdict(item) for item in load_results],
        "optimization": asdict(optimization),
        "quality": {
            "ok": quality.ok,
            "threshold": quality.threshold,
            "tables_checked": quality.tables_checked,
            "failing_tables": quality.failing_tables,
        },
    }

    config.report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = config.report_dir / "pipeline_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if not quality.ok:
        logger.error(f"Quality checks FAILED: {quality.failing_tables}")
        raise RuntimeError(
            f"Quality checks failed for tables: {', '.join(quality.failing_tables)}"
        )

    if not config.keep_downloads and config.download_dir.exists():
        shutil.rmtree(config.download_dir, ignore_errors=True)
    if not config.keep_extracted and config.extract_dir.exists():
        shutil.rmtree(config.extract_dir, ignore_errors=True)

    return summary
