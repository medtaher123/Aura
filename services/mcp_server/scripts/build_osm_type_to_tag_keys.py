#!/usr/bin/env python3
"""
Read ALL DISTINCT TAG KEYS from osm_tags_and_infra.txt and assign each key to a type
(amenity, building, landuse, industrial, shop, leisure, tourism, healthcare, etc.).
Writes type_to_tag_keys.json and tag_key_to_type.json for use by the infrastructure tool.

Usage:
  python scripts/build_osm_type_to_tag_keys.py [path/to/osm_tags_and_infra.txt]
  Output: utils/type_to_tag_keys.json, utils/tag_key_to_type.json
"""

import json
import os
import re
import sys
from pathlib import Path

# Types we recognize; tag keys from OSM that map to their own type name
PRIMARY_TAG_TYPES = {
    "amenity", "building", "landuse", "industrial", "shop", "leisure", "tourism",
    "office", "highway", "man_made", "historic", "craft", "military",
}

# Prefix rules: key prefix -> type name
PREFIX_TO_TYPE = [
    (r"^addr:", "address"),
    (r"^name:", "name"),
    (r"^opening_hours", "opening_hours"),
    (r"^contact:", "contact"),
    (r"^source:", "source"),
    (r"^ref:", "ref"),
    (r"^wikipedia:", "wikipedia"),
    (r"^wikidata:", "wikidata"),
    (r"^phone", "contact"),
    (r"^email", "contact"),
    (r"^website", "contact"),
    (r"^height", "building"),
    (r"^levels", "building"),
    (r"^roof:", "building"),
    (r"^construction:", "building"),
    (r"^railway:", "transport"),
    (r"^aeroway:", "transport"),
    (r"^public_transport", "transport"),
    (r"^waterway:", "water"),
    (r"^natural:", "natural"),
    (r"^power:", "power"),
    (r"^emergency:", "emergency"),
]

# Exact key -> type (for keys that don't match primary or prefix)
EXTRA_KEY_TO_TYPE = {
    "capacity": "amenity",
    "operator": "operator",
    "brand": "commercial",
    "cuisine": "amenity",
    "diet": "amenity",
    "religion": "religion",
    "denomination": "religion",
}


def classify_tag_key(key: str) -> str | None:
    """Return type for this tag key, or None to skip (other/junk)."""
    k = (key or "").strip()
    if not k or len(k) > 120:
        return None
    # Junk: numbers only, or too many special chars
    if re.match(r"^[\d.\s\-]+$", k):
        return None
    if k.startswith("(") or k in (". ' '", "2tag", "2dcode"):
        return None
    # Primary: key is a type name
    if k in PRIMARY_TAG_TYPES:
        return k
    # Prefix rules
    for pattern, type_name in PREFIX_TO_TYPE:
        if re.match(pattern, k, re.I):
            return type_name
    # Extra mapping
    if k in EXTRA_KEY_TO_TYPE:
        return EXTRA_KEY_TO_TYPE[k]
    # Known OSM keys that are not in PRIMARY (e.g. variant spellings)
    lower = k.lower()
    if lower in ("amenity", "building", "landuse", "industrial", "shop", "leisure", "tourism", "office", "highway"):
        return lower
    return None


def extract_tag_keys_from_file(path: str) -> list[str]:
    """Read osm_tags_and_infra.txt and return list of tag key lines (no header/footer)."""
    keys = []
    in_section = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            if "ALL DISTINCT TAG KEYS" in line:
                in_section = True
                continue
            if in_section:
                if "Total tag keys:" in line or "INFRA TYPE:" in line:
                    break
                stripped = line.strip()
                if stripped and stripped.replace("=", "").strip():
                    keys.append(line)
    return keys


def main():
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    default_input = repo_root / "osm_tags_and_infra.txt"
    utils_dir = repo_root / "utils"

    input_path = sys.argv[1] if len(sys.argv) > 1 else str(default_input)
    if not os.path.isfile(input_path):
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading tag keys from {input_path} ...")
    raw_keys = extract_tag_keys_from_file(input_path)
    print(f"Found {len(raw_keys)} tag key lines")

    type_to_keys: dict[str, list[str]] = {}
    key_to_type: dict[str, str] = {}

    for raw in raw_keys:
        # Line might be "key" or "  value  (count)"
        key = raw.strip()
        if not key or key.startswith("("):
            continue
        typ = classify_tag_key(key)
        if typ is None:
            continue
        type_to_keys.setdefault(typ, []).append(key)
        key_to_type[key] = typ

    # Dedupe and sort
    for t in type_to_keys:
        type_to_keys[t] = sorted(set(type_to_keys[t]))

    utils_dir.mkdir(parents=True, exist_ok=True)
    out_type_to_keys = utils_dir / "type_to_tag_keys.json"
    out_key_to_type = utils_dir / "tag_key_to_type.json"

    with open(out_type_to_keys, "w", encoding="utf-8") as f:
        json.dump(type_to_keys, f, indent=2)

    with open(out_key_to_type, "w", encoding="utf-8") as f:
        json.dump(key_to_type, f, indent=2)

    print(f"Wrote {out_type_to_keys} ({len(type_to_keys)} types)")
    print(f"Wrote {out_key_to_type} ({len(key_to_type)} keys)")
    for t in sorted(type_to_keys.keys()):
        print(f"  {t}: {len(type_to_keys[t])} keys")


if __name__ == "__main__":
    main()
