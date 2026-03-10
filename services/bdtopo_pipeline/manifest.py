"""Build source URL manifests for full-France BDTOPO downloads.

Both *full* and *differential* modes discover the edition
dynamically via the data.geopf.fr Atom feed API, so the product version
(e.g. ``3-4`` vs ``3-5``) is always resolved automatically.
Manual overrides (BDTOPO_SOURCE_URLS / BDTOPO_SOURCE_URLS_FILE)
still take precedence in any mode.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Iterable

import requests

from .utils import parse_inline_urls, read_urls_file

from .config import PipelineConfig
from .logger import get_logger

logger = get_logger("manifest")

_ATOM_NS = "http://www.w3.org/2005/Atom"
_GPF_NS = "https://data.geopf.fr/annexes/ressources/xsd/gpf_dl.xsd"
_PAGE_SIZE = 50  # api limit

# ── Atom feed with pagination ──────────────────────────────────────────


@dataclass
class _FeedEntry:
    title: str
    edition_date: str


def _fetch_atom_page(url: str, params: dict) -> tuple[ET.Element, int]:
    """Fetch one page and return (root element, total page count)."""
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    page_count = int(root.get(f"{{{_GPF_NS}}}pagecount", "1"))
    return root, page_count


def _parse_entries(
    root: ET.Element,
    title_filter: Callable[[str], bool] | None = None,
) -> list[_FeedEntry]:
    entries: list[_FeedEntry] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        date_el = entry.find(f"{{{_GPF_NS}}}editionDate")
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        if date_el is None or title_el is None:
            continue
        title = (title_el.text or "").strip()
        if title_filter and not title_filter(title):
            continue
        entries.append(
            _FeedEntry(
                title=title,
                edition_date=(date_el.text or "").strip(),
            )
        )
    return entries


def _fetch_all_entries(
    api_url: str,
    *,
    extra_params: dict | None = None,
    title_filter: Callable[[str], bool] | None = None,
) -> list[_FeedEntry]:
    """Fetch all entries across every page of a paginated Atom feed."""
    params: dict = {"limit": str(_PAGE_SIZE), "page": "1"}
    if extra_params:
        params.update(extra_params)

    # first page
    root, page_count = _fetch_atom_page(api_url, params)
    all_entries = _parse_entries(root, title_filter)

    for page in range(2, page_count + 1):
        params["page"] = str(page)
        root, _ = _fetch_atom_page(api_url, params)
        all_entries.extend(_parse_entries(root, title_filter))

    return all_entries


# ── Entry resolution ───────────────────────────────────────────────────

_FEED_PARAMS_FRA_GPKG = {"zone": "FRA", "format": "GPKG"}


def _resolve_entry(
    api_url: str,
    edition_date: str,
    title_filter: Callable[[str], bool] | None = None,
) -> str:
    """Find the best-matching entry title for *edition_date*.

    ``"latest"`` picks the entry with the highest editionDate.
    A concrete date picks the exact match or, failing that, the closest
    earlier edition.
    """
    entries = _fetch_all_entries(
        api_url,
        extra_params=_FEED_PARAMS_FRA_GPKG,
        title_filter=title_filter,
    )
    if not entries:
        raise RuntimeError(f"No matching GPKG/FRA entries found at {api_url}")

    if edition_date == "latest":
        best = max(entries, key=lambda e: e.edition_date)
        return best.title

    for e in entries:
        if e.edition_date == edition_date:
            return e.title

    candidates = [e for e in entries if e.edition_date <= edition_date]
    if candidates:
        best = max(candidates, key=lambda e: e.edition_date)
        logger.warning(
            "No exact edition for %s; falling back to %s",
            edition_date,
            best.edition_date,
        )
        return best.title

    raise RuntimeError(f"No edition found at or before {edition_date} in {api_url}")


# ── Differential mode ─────────────────────────────────────────────────


def _fetch_diff_download_urls(api_url: str, entry_title: str) -> list[str]:
    """Fetch the sub-resource feed for *entry_title* and return download URLs."""
    resp = requests.get(f"{api_url}/{entry_title}", timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    urls: list[str] = []
    entries = root.findall(f"{{{_ATOM_NS}}}entry") or [root]
    for entry in entries:
        link = entry.find(f"{{{_ATOM_NS}}}link")
        if link is not None:
            href = link.get("href", "").strip()
            if href:
                urls.append(href)

    if not urls:
        raise RuntimeError(f"No download links found in sub-resource {entry_title}")
    return urls


def _discover_differential_urls(config: PipelineConfig) -> list[str]:
    api_url = config.diff_api_resource_url
    entry_title = _resolve_entry(api_url, config.edition_date)
    logger.info("Differential edition resolved to: %s", entry_title)

    urls = _fetch_diff_download_urls(api_url, entry_title)
    logger.info("Discovered %d download URL(s) for %s", len(urls), entry_title)
    return urls


# ── Full mode ──────────────────────────────────────────────────────────

_FULL_TITLE_REQUIRED_TOKENS = ("TOUSTHEMES", "GPKG")


def _is_full_france_entry(title: str) -> bool:
    return all(tok in title for tok in _FULL_TITLE_REQUIRED_TOKENS)


def _probe_part_urls(
    entry_title: str,
    max_parts: int,
    timeout: float = 5.0,
) -> list[str]:
    """HEAD-probe multi-part archive URLs and return those that exist."""
    base = (
        f"https://data.geopf.fr/telechargement/download/BDTOPO/"
        f"{entry_title}/{entry_title}.7z"
    )
    urls: list[str] = []
    with requests.Session() as session:
        for index in range(1, max_parts + 1):
            url = f"{base}.{index:03d}"
            try:
                resp = session.head(url, allow_redirects=True, timeout=timeout)
            except requests.RequestException:
                break
            if not resp.ok:
                break
            urls.append(url)
    return urls


def _discover_full_urls(config: PipelineConfig, timeout: float = 5.0) -> list[str]:
    api_url = config.full_api_resource_url
    entry_title = _resolve_entry(
        api_url,
        config.edition_date,
        title_filter=_is_full_france_entry,
    )
    logger.info("Full-mode edition resolved to: %s", entry_title)

    max_parts = config.max_parts or 50
    urls = _probe_part_urls(entry_title, max_parts, timeout=timeout)
    logger.info("Discovered %d archive part(s) for %s", len(urls), entry_title)
    return urls


# ── Public API ─────────────────────────────────────────────────────────


def build_manifest(config: PipelineConfig) -> list[str]:
    """Return URLs to download for the selected pipeline mode.

    Priority:
      1. Inline URLs  (BDTOPO_SOURCE_URLS env var)
      2. File URLs    (BDTOPO_SOURCE_URLS_FILE env var)
      3. Mode-specific auto-discovery via the data.geopf.fr Atom API
    """
    if config.source_urls:
        urls = parse_inline_urls(config.source_urls)
        logger.info("Using inline URLs from BDTOPO_SOURCE_URLS")
        if not urls:
            raise ValueError("BDTOPO_SOURCE_URLS was set but no valid URL was parsed.")
        return urls

    if config.source_urls_file:
        logger.info("Using URLs from file: %s", config.source_urls_file)
        return read_urls_file(config.source_urls_file)

    if config.mode == "differential":
        logger.info("Using differential mode — discovering via Atom API")
        return _discover_differential_urls(config)

    logger.info("Using full mode — discovering via Atom API")
    return _discover_full_urls(config)


def infer_archive_name(url: str) -> str:
    clean_url = url.split("?", 1)[0]
    return clean_url.rstrip("/").split("/")[-1]


def infer_archive_names(urls: Iterable[str]) -> list[str]:
    return [infer_archive_name(url) for url in urls]
