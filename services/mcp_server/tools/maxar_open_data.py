"""
Maxar Open Data tool – query pre/post disaster satellite imagery from AWS.

Data source: https://registry.opendata.aws/maxar-open-data/
- S3 bucket: maxar-opendata (us-west-2), no AWS account required.
- STAC catalog: https://maxar-opendata.s3.amazonaws.com/events/catalog.json
- High-resolution COG imagery for disaster response, damage assessment, recovery.

Asset formats (per STAC item): visual, ms_analytic, pan_analytic are Cloud-Optimized
GeoTIFFs (.tif); there is no JPEG/PNG thumbnail asset. The UI can display a preview
by converting COG to PNG (e.g. Streamlit uses rasterio to read a small overview).
Uses pystac for catalog/collection/item traversal and asset href resolution.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import pystac
import requests
from mcp_singleton import mcp

from config import get_config
from core.logger import get_logger
from utils.contracts import ToolArtifacts, ToolResponse

logger = get_logger(__name__)


def _maxar_base_url() -> str:
    """Base URL (scheme + netloc) from configured Maxar STAC catalog URL."""
    parsed = urlsplit(get_config().maxar_stac_catalog_url)
    return f"{parsed.scheme}://{parsed.netloc}"

# Month name to number for parsing event IDs (e.g. "May24" -> 5, "Sept-2023" -> 9).
_MONTH_PATTERNS = [
    (r"\bjan(?:uary)?[\.\-]?(\d{2,4})?\b", 1),
    (r"\bfeb(?:ruary)?[\.\-]?(\d{2,4})?\b", 2),
    (r"\bmar(?:ch)?[\.\-]?(\d{2,4})?\b", 3),
    (r"\bapr(?:il)?[\.\-]?(\d{2,4})?\b", 4),
    (r"\bmay[\.\-]?(\d{2,4})?\b", 5),
    (r"\bjun(?:e)?[\.\-]?(\d{2,4})?\b", 6),
    (r"\bjul(?:y)?[\.\-]?(\d{2,4})?\b", 7),
    (r"\baug(?:ust)?[\.\-]?(\d{2,4})?\b", 8),
    (r"\bsep(?:t(?:ember)?)?[\.\-]?(\d{2,4})?\b", 9),
    (r"\boct(?:ober)?[\.\-]?(\d{2,4})?\b", 10),
    (r"\bnov(?:ember)?[\.\-]?(\d{2,4})?\b", 11),
    (r"\bdec(?:ember)?[\.\-]?(\d{2,4})?\b", 12),
]

# Country name -> search keywords for matching event_id (case-insensitive).
_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "brazil": ["brazil"],
    "turkey": ["turkey", "turkiye", "kahramanmaras"],
    "morocco": ["morocco"],
    "spain": ["spain"],
    "italy": ["italy", "romagna", "emilia"],
    "usa": ["usa", "united states", "texas", "florida", "hawaii", "maui", "kentucky", "california", "los angeles"],
    "us": ["usa", "united states", "texas", "florida", "hawaii", "maui", "kentucky", "california", "los angeles"],
    "united states": ["usa", "united states", "texas", "florida", "hawaii", "maui", "kentucky", "california", "los angeles"],
    "pakistan": ["pakistan"],
    "nepal": ["nepal"],
    "india": ["india"],
    "indonesia": ["indonesia"],
    "thailand": ["thailand"],
    "myanmar": ["myanmar", "burma"],
    "bangladesh": ["bangladesh", "bengal"],
    "sri lanka": ["sri lanka", "srilanka", "lanka"],
    "libya": ["libya"],
    "kenya": ["kenya"],
    "nigeria": ["nigeria"],
    "sudan": ["sudan"],
    "gambia": ["gambia"],
    "south africa": ["southafrica", "south africa"],
    "drc": ["drc", "drcongo", "congo", "kalehe"],
    "dr congo": ["drc", "drcongo", "congo", "kalehe"],
    "new zealand": ["newzealand", "new zealand"],
    "canada": ["canada", "nwt", "bc", "mcdougall"],
    "belize": ["belize"],
    "iceland": ["iceland"],
    "georgia": ["georgia", "shovi"],
    "vanuatu": ["vanuatu"],
    "tonga": ["tonga"],
    "ghana": ["ghana"],
    "afghanistan": ["afghanistan"],
    "marshall": ["marshall"],
    "japan": ["japan"],
    "france": ["france"],
    "mexico": ["mexico"],
    "puerto rico": ["puertorico", "puerto rico"],
}


def _normalize_country(country: str) -> list[str]:
    """Return list of keywords to match in event_id for the given country."""
    c = (country or "").strip().lower()
    if not c:
        return []
    if c in _COUNTRY_KEYWORDS:
        return _COUNTRY_KEYWORDS[c]
    return [c]


def _event_id_matches_country(event_id: str, country: str) -> bool:
    """True if event_id (case-insensitive) contains any of the country keywords."""
    keywords = _normalize_country(country)
    if not keywords:
        return True
    e = event_id.lower()
    return any(kw in e for kw in keywords)


def _two_digit_to_year(yy: int) -> int:
    """Interpret 2-digit yy as year: 00-50 -> 2000s, 51-99 -> 1900s."""
    return 2000 + yy if yy < 50 else 1900 + yy


# Month names (abbrev and full) for year extraction — order so longer matches first.
_MONTH_REGEX = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)


def _years_from_event_id(event_id: str) -> list[int]:
    """Extract possible years from event_id; covers many formats (May24, indonesia21, Jan-2024, 8Aug23, etc.)."""
    years: list[int] = []
    # 4-digit years: 2025, 2022, 2017, 2015
    for m in re.finditer(r"\b(19\d{2}|20\d{2})\b", event_id):
        y = int(m.group(1))
        if 1990 <= y <= 2030:
            years.append(y)
    # Month + 4-digit year: Jan-2024, Nov-2025, Sept-2023, Apr-2015, Oct-2017, Dec-2023, March-2025
    for m in re.finditer(_MONTH_REGEX + r"[\.\-](\d{4})\b", event_id, re.I):
        y = int(m.group(1))
        if 1990 <= y <= 2030:
            years.append(y)
    # Month + 2-digit year: May24, June24, Dec15, Dec17, Aug23, Aug-23, may23, Oct24
    for m in re.finditer(_MONTH_REGEX + r"[\.\-]?(\d{2})\b", event_id, re.I):
        yy = int(m.group(1))
        years.append(_two_digit_to_year(yy))
    # Digit + month + 2-digit year: 8Aug23
    for m in re.finditer(r"\d{1,2}" + _MONTH_REGEX + r"(\d{2})\b", event_id, re.I):
        yy = int(m.group(1))
        years.append(_two_digit_to_year(yy))
    # 2 digits after . or -: earthquake-23, -21-Update, 5-8-23 (last segment as year)
    for m in re.finditer(r"[\.\-](\d{2})\b", event_id):
        yy = int(m.group(1))
        if 0 <= yy <= 99:
            years.append(_two_digit_to_year(yy))
    # Word + 2-digit year (no separator): indonesia21, Earthquake22, Flooding23, volcano21, flooding22
    for m in re.finditer(r"[a-zA-Z](\d{2})\b", event_id):
        yy = int(m.group(1))
        if 0 <= yy <= 99:
            years.append(_two_digit_to_year(yy))
    # Fallback: 2 digits at end of string
    if not years and re.search(r"\d{2}$", event_id):
        m = re.search(r"(\d{2})$", event_id)
        if m:
            yy = int(m.group(1))
            years.append(_two_digit_to_year(yy))
    return list(dict.fromkeys(years)) if years else []


def _month_from_event_id(event_id: str) -> Optional[int]:
    """Extract month (1-12) from event_id if present."""
    e = event_id.lower()
    for pattern, month in _MONTH_PATTERNS:
        if re.search(pattern, e):
            return month
    return None


# Disaster/event type keywords to extract from event_id (e.g. Brazil-Flooding-May24 -> Flooding).
_EVENT_TYPE_KEYWORDS = [
    "flooding", "floods", "wildfires", "wildfire", "cyclone", "hurricane", "earthquake",
    "earthquakes", "landslide", "volcanic", "volcano", "eruption", "drought", "storm", "storms",
    "tornado", "tsunami", "conflict", "dam", "collapse", "mudslide", "avalanche",
]


def _event_type_from_event_id(event_id: str) -> str:
    """Extract a human-readable event type from event_id (e.g. Brazil-Flooding-May24 -> Flooding)."""
    e = event_id.lower()
    for kw in _EVENT_TYPE_KEYWORDS:
        if kw in e:
            return kw.replace("-", " ").title()
    parts = event_id.split("-")
    if len(parts) >= 2:
        return parts[1].replace("_", " ").title()
    return "Disaster event"


def _when_occurred_from_event_id(event_id: str, year: Optional[int] = None) -> str:
    """Return a short 'when' string, e.g. 'May 2024' or '2024'."""
    month = _month_from_event_id(event_id)
    years = _years_from_event_id(event_id)
    y = year if year else (years[0] if years else None)
    if not y:
        return "Unknown date"
    month_names = ("", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December")
    if month and 1 <= month <= 12:
        return f"{month_names[month]} {y}"
    return str(y)


def _event_id_matches_date(event_id: str, year: int, month: Optional[int]) -> bool:
    """True if event_id matches the given year and optional month."""
    years = _years_from_event_id(event_id)
    if not years and year:
        return False
    if years and year not in years:
        return False
    if month is not None:
        event_month = _month_from_event_id(event_id)
        if event_month is not None and event_month != month:
            return False
    return True


def _event_ids_from_root_catalog(root: pystac.Catalog) -> list[str]:
    """Extract event (child) IDs from root catalog using pystac."""
    event_ids: list[str] = []
    for link in root.get_child_links():
        href = link.get_absolute_href() if hasattr(link, "get_absolute_href") else getattr(link, "target", None)
        title = getattr(link, "title", None)
        if isinstance(href, str) and "/" in href:
            parts = href.rstrip("/").replace("/collection.json", "").replace("/catalog.json", "").split("/")
            for part in reversed(parts):
                if part and part not in (".",):
                    event_ids.append(part)
                    break
        elif isinstance(title, str) and title.strip():
            event_ids.append(title.strip())
    return event_ids


def get_event_ids_by_location_and_date(
    country: str,
    year: int,
    month: Optional[int] = None,
) -> list[str]:
    """
    Return event IDs from the Maxar Open Data catalog that match the given
    location (country) and date (year, optional month).

    Uses pystac to load the root catalog; matching is heuristic by event ID string.
    """
    try:
        root = pystac.Catalog.from_file(get_config().maxar_stac_catalog_url)
        root.resolve_links()
    except Exception as e:
        logger.warning(f"Maxar catalog load failed: {e}")
        return []
    event_ids = _event_ids_from_root_catalog(root)
    out: list[str] = []
    for eid in event_ids:
        if not _event_id_matches_country(eid, country):
            continue
        if not _event_id_matches_date(eid, year, month):
            continue
        out.append(eid)
    return out


def _open_event_collection(event_id: str) -> Optional[pystac.Catalog | pystac.Collection]:
    """Open one event's STAC collection/catalog with pystac. Returns None on failure."""
    base = _maxar_base_url()
    for path in (f"events/{event_id}/collection.json", f"events/{event_id}/catalog.json"):
        url = f"{base}/{path}"
        try:
            obj = pystac.STACObject.from_file(url)
            if isinstance(obj, (pystac.Catalog, pystac.Collection)):
                obj.resolve_links()
                return obj
        except Exception as e:
            logger.debug(f"Maxar pystac from_file {path}: {e}", exc_info=True)
            # Fallback: fetch with requests and parse with pystac (avoids fsspec/HTTP layer issues)
            try:
                r = requests.get(url, timeout=get_config().maxar_request_timeout)
                r.raise_for_status()
                data = r.json()
                stac_type = data.get("type", "").lower()
                if stac_type == "collection":
                    obj = pystac.Collection.from_dict(data, href=url)
                elif stac_type == "catalog":
                    obj = pystac.Catalog.from_dict(data, href=url)
                else:
                    continue
                obj.set_root(obj)
                obj.resolve_links()
                return obj
            except Exception as e2:
                logger.debug(f"Maxar requests fallback {path}: {e2}", exc_info=True)
            continue
    logger.warning(f"Maxar collection open failed for {event_id}")
    return None


def _fetch_stac_with_requests(url: str) -> Optional[pystac.STACObject]:
    """Fetch a STAC JSON from url with requests and return a pystac object. Returns None on failure."""
    try:
        r = requests.get(url, timeout=get_config().maxar_request_timeout)
        r.raise_for_status()
        data = r.json()
        stac_type = (data.get("type") or "").lower()
        if stac_type == "collection":
            obj = pystac.Collection.from_dict(data, href=url)
        elif stac_type == "catalog":
            obj = pystac.Catalog.from_dict(data, href=url)
        elif stac_type == "feature":
            obj = pystac.Item.from_dict(data, href=url)
        else:
            return None
        return obj
    except Exception as e:
        logger.debug(f"Maxar fetch {url[:80]}: {e}")
        return None


def _items_from_collection(coll: pystac.Catalog | pystac.Collection, limit: int) -> list[pystac.Item]:
    """Collect STAC items by walking child links and item links with requests (no pystac from_file)."""
    items: list[pystac.Item] = []
    root = coll.get_root() or coll
    try:
        for child_link in coll.get_child_links():
            if len(items) >= limit:
                break
            child_href = child_link.get_absolute_href() or urljoin(coll.self_href or "", child_link.href or "")
            if not child_href:
                continue
            child_obj = _fetch_stac_with_requests(child_href)
            if not isinstance(child_obj, (pystac.Catalog, pystac.Collection)):
                continue
            child_obj.set_root(root)
            child_obj.resolve_links()
            for item_link in child_obj.get_item_links():
                if len(items) >= limit:
                    break
                item_href = item_link.get_absolute_href() or urljoin(child_obj.self_href or "", item_link.href or "")
                if not item_href:
                    continue
                item_obj = _fetch_stac_with_requests(item_href)
                if not isinstance(item_obj, pystac.Item):
                    continue
                item_obj.set_parent(child_obj)
                items.append(item_obj)
    except Exception as e:
        logger.warning(f"_items_from_collection failed: {e}", exc_info=True)
        # Return partial list so the tool can still return results for other events
    return items


def _asset_hrefs_from_item(item: pystac.Item, prefer: str = "visual") -> list[str]:
    """Extract absolute asset hrefs from a pystac Item (all imagery assets)."""
    try:
        item.make_asset_hrefs_absolute()
    except Exception:
        pass
    urls: list[str] = []
    assets = item.get_assets()
    if prefer in assets:
        href = assets[prefer].get_absolute_href()
        if href:
            urls.append(href)
    for key in ("thumbnail", "visual", "ms_analytic", "pan_analytic"):
        if key not in assets or key == prefer:
            continue
        href = assets[key].get_absolute_href()
        if href and href not in urls:
            urls.append(href)
    return urls


def _display_thumbnails_from_item(item: pystac.Item) -> list[str]:
    """Return only natural-color asset hrefs for UI preview (visual first, then thumbnail). Avoids mixing in ms_analytic/pan_analytic so all thumbnails look consistent."""
    try:
        item.make_asset_hrefs_absolute()
    except Exception:
        pass
    out: list[str] = []
    assets = item.get_assets()
    for key in ("visual", "thumbnail"):
        if key not in assets:
            continue
        href = assets[key].get_absolute_href()
        if href and href not in out:
            out.append(href)
    return out


@mcp.tool()
def maxar_open_data_imagery_tool(
    country: str,
    year: int,
    month: int | None = None,
    max_events: int = 5,
    max_items_per_event: int = 5,
    asset_type: str = "visual",
) -> ToolResponse:
    """
    Get Maxar Open Data satellite imagery for disasters in a given country and date.

    Fetches event IDs that match the location (country) and date (year, optional month),
    then retrieves imagery (COG/thumbnail URLs) for those events using the STAC catalog.

    country: Country name (e.g. "Brazil", "Turkey", "Morocco", "USA").  
    year: Year (e.g. 2024, 2023).
    month: Optional month 1-12 (e.g. 5 for May). If omitted, all events in that year are considered.
    max_events: Maximum number of matching events to load imagery for (default 5, max 20).
    max_items_per_event: Maximum STAC items (tiles) per event (default 5, max 15).
    asset_type: Preferred asset: "visual" (RGB COG), "thumbnail", "ms_analytic", or "pan_analytic" (default "visual").
    """
    country = (country or "").strip()
    if not country:
        return ToolResponse(
            tool_name="maxar_open_data_imagery_tool",
            message="country is required.",
            error=True,
        )
    try:
        year = int(year)
    except (TypeError, ValueError):
        return ToolResponse(
            tool_name="maxar_open_data_imagery_tool",
            message="year must be an integer (e.g. 2024).",
            error=True,
        )
    month_val: Optional[int] = None
    if month is not None:
        try:
            month_val = int(month)
            if month_val < 1 or month_val > 12:
                month_val = None
        except (TypeError, ValueError):
            month_val = None

    event_ids = get_event_ids_by_location_and_date(country, year, month_val)
    if not event_ids:
        return ToolResponse(
            tool_name="maxar_open_data_imagery_tool",
            message=f"No Maxar Open Data events found for {country} in {year}" + (f"-{month_val:02d}" if month_val else ""),
            data={"country": country, "year": year, "month": month_val, "event_ids": []},
            error=False,
        )

    max_events_cap = get_config().maxar_max_events_list
    max_items_cap = get_config().maxar_max_items_per_event
    cap_events = min(max(1, int(max_events)), max_events_cap)
    cap_items = min(max(1, int(max_items_per_event)), max_items_cap)
    event_ids = event_ids[:cap_events]

    all_thumbnails: list[str] = []
    all_urls: list[str] = []
    events_data: list[dict[str, Any]] = []

    for event_id in event_ids:
        coll = _open_event_collection(event_id)
        if not coll:
            continue
        items = _items_from_collection(coll, limit=cap_items)
        thumbnails: list[str] = []
        urls: list[str] = []
        image_summaries: list[dict[str, Any]] = []
        for item in items:
            asset_urls = _asset_hrefs_from_item(item, prefer=asset_type)
            display_urls = _display_thumbnails_from_item(item)
            for u in asset_urls:
                if u not in all_urls:
                    all_urls.append(u)
            for u in display_urls:
                if u not in thumbnails:
                    thumbnails.append(u)
            dt = item.get_datetime()
            image_summaries.append({
                "id": item.id,
                "datetime": str(dt) if dt else "",
                "bbox": list(item.bbox) if item.bbox else None,
                "asset_hrefs": asset_urls[:3],
            })
        for u in thumbnails:
            if u not in all_thumbnails:
                all_thumbnails.append(u)
        title = getattr(coll, "title", None) or event_id
        description = getattr(coll, "description", None) or ""
        event_type = _event_type_from_event_id(event_id)
        when_occurred = _when_occurred_from_event_id(event_id, year)
        imagery_desc = (
            f"Natural-color satellite imagery (pre- and/or post-event) for damage assessment; "
            f"{len(items)} scene(s) displayed."
        )
        events_data.append({
            "event_id": event_id,
            "title": title,
            "description": (description or "")[:300],
            "event_type": event_type,
            "when_occurred": when_occurred,
            "imagery_description": imagery_desc,
            "item_count": len(items),
            "items": image_summaries,
        })

    if not events_data:
        return ToolResponse(
            tool_name="maxar_open_data_imagery_tool",
            message=f"Found {len(event_ids)} event(s) for {country} {year} but could not load imagery.",
            data={"country": country, "year": year, "month": month_val, "event_ids": event_ids, "events": []},
            error=False,
        )

    total_items = sum(e["item_count"] for e in events_data)
    event_summaries: list[str] = []
    for e in events_data:
        summary = (
            f"**{e['title']}** — Type: {e['event_type']}. "
            f"When: {e['when_occurred']}. "
            f"{e['imagery_description']}"
        )
        desc = (e.get("description") or "").strip()
        if desc:
            summary += f" Collection: {desc[:120]}{'…' if len(desc) > 120 else ''}"
        event_summaries.append(summary)
    message = (
        f"Retrieved imagery for {len(events_data)} event(s) in {country} ({year}): {total_items} image(s) total.\n\n"
        + "\n\n".join(event_summaries)
    )
    artifacts = ToolArtifacts(thumbnails=all_thumbnails[:20], urls=all_urls[:30])
    return ToolResponse(
        tool_name="maxar_open_data_imagery_tool",
        message=message,
        artifacts=artifacts,
        country=country,
        data={
            "country": country,
            "year": year,
            "month": month_val,
            "event_ids": event_ids,
            "events": events_data,
            "catalog_url": get_config().maxar_stac_catalog_url,
        },
        error=False,
    )
