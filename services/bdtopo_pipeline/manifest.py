"""Build source URL manifests for full-France BDTOPO downloads.

For *full* mode the URLs are generated from a template + part count.
For *differential* mode the URLs are discovered automatically via the
data.geopf.fr Atom feed API (no manual URL input required).
Manual overrides (BDTOPO_SOURCE_URLS / BDTOPO_SOURCE_URLS_FILE) still
take precedence in any mode.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import requests

from .config import PipelineConfig
from .logger import get_logger

logger = get_logger("manifest")

_ATOM_NS = "http://www.w3.org/2005/Atom"
_GPF_NS = "https://data.geopf.fr/annexes/ressources/xsd/gpf_dl.xsd"


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


# ── API discovery ──────────────────────────────────────────────────────


def _fetch_atom_feed(url: str, params: dict | None = None) -> ET.Element:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def _discover_latest_diff_entry(api_url: str) -> str:
    """Return the entry title of the most recent differential edition.

    The API returns entries sorted by edition date; we pick the one with
    the highest editionDate.
    """
    root = _fetch_atom_feed(
        api_url,
        params={
            "zone": "FRA",
            "format": "GPKG",
            "limit": "50",
        },
    )

    best_date = ""
    best_title = ""
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        date_el = entry.find(f"{{{_GPF_NS}}}editionDate")
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        if date_el is None or title_el is None:
            continue
        edition_date = (date_el.text or "").strip()
        title = (title_el.text or "").strip()
        if edition_date > best_date:
            best_date = edition_date
            best_title = title

    if not best_title:
        raise RuntimeError(f"No GPKG/FRA differential entries found at {api_url}")
    return best_title


def _discover_diff_entry_for_date(api_url: str, edition_date: str) -> str:
    """Return the entry title whose editionDate matches *edition_date*.

    Falls back to a best-effort match: if the exact date isn't found we
    pick the entry whose editionDate is closest but not after the
    requested date (i.e. the most recent edition that was available at
    *edition_date*).
    """
    root = _fetch_atom_feed(
        api_url,
        params={
            "zone": "FRA",
            "format": "GPKG",
            "limit": "50",
        },
    )

    exact: str | None = None
    best_date = ""
    best_title = ""

    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        date_el = entry.find(f"{{{_GPF_NS}}}editionDate")
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        if date_el is None or title_el is None:
            continue
        ed = (date_el.text or "").strip()
        title = (title_el.text or "").strip()

        if ed == edition_date:
            exact = title
            break
        if ed <= edition_date and ed > best_date:
            best_date = ed
            best_title = title

    if exact:
        return exact
    if best_title:
        logger.warning(
            "No exact differential edition for %s; "
            "falling back to closest earlier edition %s",
            edition_date,
            best_date,
        )
        return best_title

    raise RuntimeError(
        f"No differential edition found at or before {edition_date} in {api_url}"
    )


def _discover_diff_download_urls(api_url: str, entry_title: str) -> list[str]:
    """Fetch the sub-resource feed for *entry_title* and return download URLs."""
    root = _fetch_atom_feed(f"{api_url}/{entry_title}")

    urls: list[str] = []
    entries = root.findall(f"{{{_ATOM_NS}}}entry")
    if not entries or len(entries) == 0:
        entries = [root]
    for entry in entries:
        link = entry.find(f"{{{_ATOM_NS}}}link")
        if link is not None:
            href = link.get("href", "").strip()
            if href:
                urls.append(href)

    if not urls:
        raise RuntimeError(f"No download links found in sub-resource {entry_title}")
    return urls


def discover_differential_urls(config: PipelineConfig) -> list[str]:
    """Auto-discover download URLs for differential mode via the API."""
    api_url = config.diff_api_resource_url

    today_str = config.edition_date
    if today_str == "latest":
        entry_title = _discover_latest_diff_entry(api_url)
    else:
        entry_title = _discover_diff_entry_for_date(api_url, today_str)

    logger.info("Differential edition resolved to: %s", entry_title)
    urls = _discover_diff_download_urls(api_url, entry_title)
    logger.info("Discovered %d download URL(s) for %s", len(urls), entry_title)
    return urls


# ── Public API ─────────────────────────────────────────────────────────
def collect_urls(config, max_parts: int = 50, timeout: float = 5.0) -> list[str]:
    """Collect URLs for the given configuration."""
    urls: list[str] = []

    with requests.Session() as session:
        for index in range(1, max_parts + 1):
            url = config.source_template.format(
                edition_date=config.edition_date,
                part=f"{index:03d}",
            )

            try:
                response = session.head(url, allow_redirects=True, timeout=timeout)
            except requests.RequestException:
                break

            if not response.ok:
                break

            urls.append(url)

    return urls


def build_manifest(config: PipelineConfig) -> list[str]:
    """
    Return URLs to download for the selected pipeline mode.

    Priority:
      1. Inline URLs  (BDTOPO_SOURCE_URLS env var)
      2. File URLs    (BDTOPO_SOURCE_URLS_FILE env var)
      3. Mode-specific auto-discovery:
         - full:            collect URLs from the template
         - differential:    auto-discover URLs from the data.geopf.fr Atom API
    """
    if config.source_urls_inline:
        urls = _parse_inline_urls(config.source_urls_inline)
        if not urls:
            raise ValueError("BDTOPO_SOURCE_URLS was set but no valid URL was parsed.")
        return urls

    if config.source_urls_file:
        return _read_urls_file(config.source_urls_file)

    if config.mode == "differential":
        return discover_differential_urls(config)

    # Full mode
    return collect_urls(config)


def infer_archive_name(url: str) -> str:
    clean_url = url.split("?", 1)[0]
    return clean_url.rstrip("/").split("/")[-1]


def infer_archive_names(urls: Iterable[str]) -> list[str]:
    return [infer_archive_name(url) for url in urls]
