"""CLI entrypoint for BDTOPO full-France ingestion workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    # Allow direct execution: python services/bdtopo_pipeline/run_pipeline.py
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from bdtopo_pipeline.config import get_config
from bdtopo_pipeline.pipeline import run_pipeline
from bdtopo_pipeline.logger import get_logger

logger = get_logger("run_pipeline")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BDTOPO ingestion pipeline.")
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "express", "differential"],
        help="Ingestion mode.",
    )
    parser.add_argument(
        "--edition-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="BDTOPO edition date (YYYY-MM-DD).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = get_config(mode=args.mode, edition_date=args.edition_date)
    summary = run_pipeline(config)
    logger.info(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
