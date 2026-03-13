"""7z extraction helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess

from tqdm import tqdm

from .logger import get_logger

logger = get_logger("extractor")


def _detect_entry_archive(archives: list[Path]) -> Path:
    if len(archives) == 1:
        return archives[0]
    ordered = sorted(archives)
    for archive in ordered:
        if archive.name.endswith(".001"):
            return archive
    logger.error("No entry archive (.001) found among %d archives", len(archives))
    raise ValueError("No entry archive found.")


def extract_archives(
    archives: list[Path], output_dir: Path, *, timeout_seconds: int = 7200
) -> list[Path]:
    if not archives:
        logger.error("extract_archives called with empty archive list")
        raise ValueError("No archives provided for extraction.")

    output_dir.mkdir(parents=True, exist_ok=True)
    entry_archive = _detect_entry_archive(archives)

    total_size = sum(a.stat().st_size for a in archives)
    logger.info(
        f"Extracting {entry_archive.name} ({len(archives)} parts, "
        f"{total_size / 1024**3:.1f} GB total) -> {output_dir}"
    )

    command = [
        "7z",
        "x",
        "-y",
        "-bsp1",
        f"-o{output_dir}",
        str(entry_archive),
    ]

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    with tqdm(total=100, desc="Extracting", unit="%", leave=False) as pbar:
        last_pct = 0
        for line in process.stdout or []:
            line = line.strip()
            if "%" in line:
                try:
                    pct = int(line.split("%")[0].strip().split()[-1])
                    if pct > last_pct:
                        pbar.update(pct - last_pct)
                        last_pct = pct
                except (ValueError, IndexError):
                    pass

    returncode = process.wait(timeout=timeout_seconds)
    if returncode != 0:
        logger.error("7z exited with code %d for %s", returncode, entry_archive.name)
        raise RuntimeError(f"7z extraction failed with exit code {returncode}")

    gpkg_files = sorted(output_dir.rglob("*.gpkg"))
    if not gpkg_files:
        logger.error("No .gpkg files in %s after extracting %s", output_dir, entry_archive.name)
        raise RuntimeError("Extraction completed but no .gpkg files were found.")

    logger.info(f"Extracted {len(gpkg_files)} .gpkg file(s)")
    return gpkg_files
