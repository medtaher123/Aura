"""Build source URL manifests for full-France BDTOPO downloads."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .config import PipelineConfig


def _read_urls_file(path: str) -> list[str]:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Source URL file not found: {file_path}")

    urls: list[str] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    if not urls:
        raise ValueError(f"Source URL file is empty: {file_path}")
    return urls


def _parse_inline_urls(raw: str) -> list[str]:
    urls: list[str] = []
    for chunk in raw.replace(",", "\n").splitlines():
        line = chunk.strip()
        if line:
            urls.append(line)
    return urls


def build_manifest(config: PipelineConfig) -> list[str]:
    """
    Return URLs to download for the selected pipeline mode.

    - full: generated from `BDTOPO_SOURCE_TEMPLATE` and part count
    - express/differential: expected from `BDTOPO_SOURCE_URLS_FILE` (or custom template)
    """
    if config.source_urls_inline:
        urls = _parse_inline_urls(config.source_urls_inline)
        if not urls:
            raise ValueError("BDTOPO_SOURCE_URLS was set but no valid URL was parsed.")
        return urls

    if config.source_urls_file:
        return _read_urls_file(config.source_urls_file)

    if config.mode in {"express", "differential"}:
        raise ValueError(
            "Express and differential modes require BDTOPO_SOURCE_URLS_FILE "
            "with one URL per line."
        )

    urls: list[str] = []
    for index in range(1, config.full_france_part_count + 1):
        urls.append(
            config.source_template.format(
                edition_date=config.edition_date,
                part=f"{index:03d}",
            )
        )
    return urls


def infer_archive_name(url: str) -> str:
    clean_url = url.split("?", 1)[0]
    return clean_url.rstrip("/").split("/")[-1]


def infer_archive_names(urls: Iterable[str]) -> list[str]:
    return [infer_archive_name(url) for url in urls]
