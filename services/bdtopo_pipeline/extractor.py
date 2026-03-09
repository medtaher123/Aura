"""7z extraction helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Iterable


def _detect_entry_archive(archives: Iterable[Path]) -> Path:
    ordered = sorted(archives)
    for archive in ordered:
        if archive.name.endswith(".001"):
            return archive
    return ordered[0]


def extract_archives(archives: list[Path], output_dir: Path) -> list[Path]:
    if not archives:
        raise ValueError("No archives provided for extraction.")

    output_dir.mkdir(parents=True, exist_ok=True)
    entry_archive = _detect_entry_archive(archives)
    command = [
        "7z",
        "x",
        "-y",
        f"-o{output_dir}",
        str(entry_archive),
    ]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(
            "7z extraction failed.\n"
            f"stdout:\n{process.stdout}\n"
            f"stderr:\n{process.stderr}"
        )

    gpkg_files = sorted(output_dir.rglob("*.gpkg"))
    if not gpkg_files:
        raise RuntimeError("Extraction completed but no .gpkg files were found.")
    return gpkg_files

