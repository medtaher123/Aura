#!/usr/bin/env python3
"""
Print an overview of the Maxar Open Data catalog (events and optional details).

Usage:
  python scripts/maxar_open_data_overview.py
  python scripts/maxar_open_data_overview.py --filter flood
  python scripts/maxar_open_data_overview.py --limit 20 --details 3
  python scripts/maxar_open_data_overview.py --json

Requires: requests (pip install requests)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("Install requests: pip install requests", file=sys.stderr)
    sys.exit(1)

CATALOG_URL = "https://maxar-opendata.s3.amazonaws.com/events/catalog.json"
TIMEOUT = 30


def fetch_catalog() -> dict[str, Any] | None:
    try:
        r = requests.get(CATALOG_URL, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Failed to fetch catalog: {e}", file=sys.stderr)
        return None


def event_ids_from_catalog(catalog: dict[str, Any]) -> list[str]:
    ids = []
    for link in catalog.get("links") or []:
        if link.get("rel") != "child":
            continue
        href = (link.get("href") or "").strip()
        title = (link.get("title") or "").strip()
        # href can be ./Event-Name/collection.json or .../Event-Name/catalog.json
        if "/" in href:
            # last path part is collection.json or catalog.json; event id is the folder name
            parts = href.rstrip("/").split("/")
            for part in reversed(parts):
                if part and part not in ("collection.json", "catalog.json", "."):
                    ids.append(part)
                    break
        elif title:
            ids.append(title)
    return ids


def fetch_event_catalog(event_id: str) -> dict[str, Any] | None:
    base = CATALOG_URL.replace("/events/catalog.json", "")
    # Try collection.json first (current catalog structure), then catalog.json
    for path in (f"events/{event_id}/collection.json", f"events/{event_id}/catalog.json"):
        url = f"{base}/{path}"
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception:
            continue
    return None


def count_items_in_collection(collection: dict[str, Any]) -> int:
    return sum(1 for link in (collection.get("links") or []) if link.get("rel") == "item")


def main() -> int:
    ap = argparse.ArgumentParser(description="Overview of Maxar Open Data catalog")
    ap.add_argument("--filter", "-f", type=str, help="Filter event IDs by substring (e.g. flood, turkey)")
    ap.add_argument("--limit", "-n", type=int, default=0, help="Max number of events to list (0 = all)")
    ap.add_argument("--details", "-d", type=int, default=0, metavar="N", help="Fetch details for first N events (title, item count)")
    ap.add_argument("--json", action="store_true", help="Output JSON only (event_ids and optional details)")
    args = ap.parse_args()

    catalog = fetch_catalog()
    if not catalog:
        return 1

    event_ids = event_ids_from_catalog(catalog)
    if args.filter:
        q = args.filter.strip().lower()
        event_ids = [e for e in event_ids if q in e.lower()]
    if args.limit > 0:
        event_ids = event_ids[: args.limit]

    if args.json:
        out = {"catalog_url": CATALOG_URL, "total_events": len(event_ids), "event_ids": event_ids}
        if args.details > 0:
            details_list = []
            for eid in event_ids[: args.details]:
                col = fetch_event_catalog(eid)
                if col:
                    details_list.append({
                        "event_id": eid,
                        "title": col.get("title") or eid,
                        "description": (col.get("description") or "")[:200],
                        "item_count": count_items_in_collection(col),
                    })
                else:
                    details_list.append({"event_id": eid, "error": "could not load"})
            out["details"] = details_list
        print(json.dumps(out, indent=2))
        return 0

    # Human-readable overview
    print("Maxar Open Data – Catalog overview")
    print("=" * 60)
    print(f"Catalog: {CATALOG_URL}")
    print(f"Total events: {len(event_ids)}")
    if args.filter:
        print(f"Filter: '{args.filter}'")
    print()
    print("Events (event_id):")
    print("-" * 60)
    for i, eid in enumerate(event_ids, 1):
        print(f"  {i:3}. {eid}")

    if args.details > 0:
        print()
        print("Details (first {} event(s)):".format(args.details))
        print("-" * 60)
        for eid in event_ids[: args.details]:
            col = fetch_event_catalog(eid)
            if col:
                title = col.get("title") or eid
                desc = (col.get("description") or "")[:120]
                n = count_items_in_collection(col)
                print(f"  {eid}")
                print(f"    Title: {title}")
                print(f"    Items: {n}")
                if desc:
                    print(f"    Description: {desc}...")
            else:
                print(f"  {eid}: (could not load)")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
