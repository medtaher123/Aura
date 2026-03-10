"""Configuration helpers for the BDTOPO ingestion pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ModeOptions = Literal["full", "express", "differential"]

_UNSET_PATH = Path("__UNSET__")


class PipelineConfig(BaseSettings):
    """BDTOPO pipeline configuration with automatic environment variable loading.

    All fields map to ``BDTOPO_*`` env vars (case-insensitive) thanks to
    ``env_prefix``.  ``mode`` and ``edition_date`` have no env-var default and
    are expected to be supplied at construction time (CLI args, ECS overrides…).
    """

    mode: ModeOptions = Field(default="full", description="Ingestion mode")
    edition_date: str = Field(
        default="latest",
        description="BDTOPO edition date (YYYY-MM-DD or 'latest')",
    )

    work_dir: Path = Field(
        default=Path("/tmp/bdtopo"),
        description="Root working directory for pipeline artifacts",
    )
    download_dir: Path = Field(
        default=_UNSET_PATH,
        description="Override download directory (default: work_dir/downloads/<edition_date>)",
    )
    extract_dir: Path = Field(
        default=_UNSET_PATH,
        description="Override extraction directory (default: work_dir/extracted/<edition_date>)",
    )
    report_dir: Path = Field(
        default=_UNSET_PATH,
        description="Override report directory (default: work_dir/reports/<edition_date>)",
    )

    database_url: str = Field(
        default="",
        description="PostGIS connection string",
    )

    source_urls: str = Field(
        default="",
        description="Inline comma-separated source URLs",
    )
    source_urls_file: str = Field(
        default="",
        description="Path to a file listing source URLs",
    )
    max_parts: int = Field(
        default=50,
        description="Number of maximum archive parts for full-France download",
    )
    diff_api_resource_url: str = Field(
        default="https://data.geopf.fr/telechargement/resource/BDTOPO-DIFF",
        description="API resource URL for differential discovery",
    )
    full_api_resource_url: str = Field(
        default="https://data.geopf.fr/telechargement/resource/BDTOPO",
        description="API resource URL for full-mode entry discovery",
    )

    keep_downloads: bool = Field(
        default=True, description="Keep downloaded archives after extraction"
    )
    keep_extracted: bool = Field(
        default=True, description="Keep extracted files after loading"
    )

    download_timeout_seconds: int = Field(
        default=90, description="Per-file download timeout"
    )
    download_max_retries: int = Field(
        default=5, description="Max download retry attempts"
    )
    download_chunk_size: int = Field(
        default=1_048_576, description="Download chunk size in bytes"
    )
    extraction_timeout_seconds: int = Field(
        default=7200, description="Extraction timeout"
    )
    quality_invalid_ratio_threshold: float = Field(
        default=0.01,
        description="Max acceptable ratio of invalid geometries",
    )

    model_config = SettingsConfigDict(
        env_prefix="BDTOPO_",
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _resolve_dirs(self) -> "PipelineConfig":
        self.work_dir = self.work_dir.resolve()
        if self.download_dir == _UNSET_PATH:
            self.download_dir = self.work_dir / "downloads" / self.edition_date
        if self.extract_dir == _UNSET_PATH:
            self.extract_dir = self.work_dir / "extracted" / self.edition_date
        if self.report_dir == _UNSET_PATH:
            self.report_dir = self.work_dir / "reports" / self.edition_date
        return self


_config_instance: Optional[PipelineConfig] = None


def get_config(**overrides) -> PipelineConfig:
    """Get or create a singleton config instance.

    Keyword arguments are forwarded to ``PipelineConfig()`` on first call
    (e.g. ``mode="full"``, ``edition_date="2025-06-01"``).
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = PipelineConfig(**overrides)
    return _config_instance


def load_config(mode: ModeOptions, edition_date: str) -> PipelineConfig:
    """Legacy helper – delegates to ``get_config``."""
    return get_config(mode=mode, edition_date=edition_date)
