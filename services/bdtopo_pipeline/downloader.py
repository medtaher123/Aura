"""Multipart HTTP downloader with retry/resume support."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Iterable

import requests

from .config import PipelineConfig
from .manifest import infer_archive_name


def _download_one(
    *,
    url: str,
    destination: Path,
    timeout_seconds: int,
    chunk_size: int,
    max_retries: int,
) -> None:
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        existing_size = destination.stat().st_size if destination.exists() else 0
        headers: dict[str, str] = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"
        try:
            with requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=timeout_seconds,
                allow_redirects=True,
            ) as response:
                if response.status_code not in (200, 206):
                    raise RuntimeError(
                        f"Unexpected HTTP status {response.status_code} for {url}"
                    )

                mode = (
                    "ab"
                    if (existing_size > 0 and response.status_code == 206)
                    else "wb"
                )
                if mode == "wb" and existing_size > 0:
                    existing_size = 0

                with destination.open(mode) as file_handle:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            file_handle.write(chunk)
                return
        except Exception as exc:  # noqa: BLE001 - retry block
            if attempt >= max_retries:
                raise RuntimeError(f"Failed to download {url}: {exc}") from exc
            sleep_seconds = min(2**attempt, 30)
            time.sleep(sleep_seconds)


def _validate_download(url: str, local_path: Path, timeout: int) -> bool:
    """Return True if local file matches remote Content-Length."""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        expected = int(resp.headers.get("Content-Length", 0))
        return expected > 0 and local_path.stat().st_size == expected
    except Exception:
        return False


def download_archives(config: PipelineConfig, urls: Iterable[str]) -> list[Path]:
    config.download_dir.mkdir(parents=True, exist_ok=True)
    local_files: list[Path] = []
    for url in urls:
        target = config.download_dir / infer_archive_name(url)
        if target.exists() and _validate_download(url, target, config.download_timeout_seconds):
            pass
        else:
            _download_one(
                url=url,
                destination=target,
                timeout_seconds=config.download_timeout_seconds,
                chunk_size=config.download_chunk_size,
                max_retries=config.download_max_retries,
            )
        local_files.append(target)
    return local_files
