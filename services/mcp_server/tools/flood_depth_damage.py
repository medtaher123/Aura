"""
Flood Depth-Damage Tool for MCP

Uses the Global flood depth-damage functions dataset to estimate damage
given a flood depth, asset class, and country.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger
from mcp_singleton import mcp
from utils.contracts import ToolResponse

logger = get_logger(__name__)

DATASET_PATH = Path(
    "/home/ubuntu/MetaplanetLLM/services/mcp_server/utils/"
    "global_flood_depth-damage_functions__30102017.xlsx"
)

ASSET_CLASS_ALIASES = {
    "residential": "residential",
    "residential building": "residential",
    "residential buildings": "residential",
    "commercial": "commercial",
    "commercial building": "commercial",
    "commercial buildings": "commercial",
    "industrial": "industrial",
    "industrial building": "industrial",
    "industrial buildings": "industrial",
    "agriculture": "agriculture",
    "agricultural": "agriculture",
    "infrastructure": "infrastructure",
    "transport": "transport",
    "transportation": "transport",
}

CONTINENT_ALIASES = {
    "europe": "europe",
    "eu": "europe",
    "north america": "north_america",
    "north_america": "north_america",
    "na": "north_america",
    "central and south america": "centr_south_america",
    "central america": "centr_south_america",
    "south america": "centr_south_america",
    "central south america": "centr_south_america",
    "central/south america": "centr_south_america",
    "centr&south america": "centr_south_america",
    "centr and south america": "centr_south_america",
    "centrandsouth america": "centr_south_america",
    "c/s america": "centr_south_america",
    "latin america": "centr_south_america",
    "asia": "asia",
    "africa": "africa",
    "oceania": "oceania",
    "australia": "oceania",
    "global": "global",
    "world": "global",
}

BASIS_ALIASES = {
    "building": "building_total",
    "total": "building_total",
    "structure": "structure",
    "content": "content",
    "land_use": "land_use_total",
    "land-use": "land_use_total",
    "landuse": "land_use_total",
    "object": "object_total",
}

AG_BASIS_OPTIONS = {"per_hectare", "per_ha", "hectare"}
AREA_BASIS_OPTIONS = {"per_m2", "m2", "sqm"}

GLOBAL_MULTIPLIER = {
    2010: 1.000,
    2011: 1.045,
    2012: 1.093,
    2013: 1.143,
    2014: 1.195,
    2015: 1.249,
    2016: 1.306,
    2017: 1.365,
    2018: 1.427,
    2019: 1.492,
    2020: 1.559,
    2021: 1.630,
    2022: 1.704,
    2023: 1.782,
    2024: 1.863,
    2025: 1.948,
    2026: 2.036,
    2027: 2.128,
    2028: 2.223,
    2029: 2.323,
    2030: 2.427,
}


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _normalize_country(value: str) -> str:
    return _normalize_text(value)


def _normalize_asset_class(value: str) -> Optional[str]:
    key = _normalize_text(value)
    if key in ASSET_CLASS_ALIASES:
        return ASSET_CLASS_ALIASES[key]
    # attempt to strip trailing "buildings"
    if key.endswith(" buildings"):
        key = key[: -len(" buildings")].strip()
        return ASSET_CLASS_ALIASES.get(key)
    return None


def _normalize_continent(value: str) -> Optional[str]:
    key = _normalize_text(value)
    return CONTINENT_ALIASES.get(key)


def _normalize_continent_from_column(value: str) -> Optional[str]:
    key = _normalize_text(value)
    key = key.replace("&", "and").replace("/", " ")
    key = " ".join(key.split())
    return _normalize_continent(key)


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _interpolate_damage(depth: float, points: List[Tuple[float, float]]) -> float:
    if not points:
        raise ValueError("Damage curve is empty.")
    points = sorted(points, key=lambda x: x[0])
    min_depth = points[0][0]
    max_depth = points[-1][0]
    if depth < min_depth or depth > max_depth:
        raise ValueError(
            f"Depth {depth} m is outside the supported range ({min_depth}-{max_depth} m)."
        )
    for d, v in points:
        if depth == d:
            return v
    for i in range(1, len(points)):
        d0, v0 = points[i - 1]
        d1, v1 = points[i]
        if d0 <= depth <= d1:
            if d1 == d0:
                return v0
            ratio = (depth - d0) / (d1 - d0)
            return v0 + ratio * (v1 - v0)
    return points[-1][1]


def _resolve_year(year: Optional[int]) -> int:
    if year is None:
        return datetime.utcnow().year
    try:
        return int(year)
    except Exception as exc:
        raise ValueError("Year must be an integer.") from exc


import pandas as pd


@lru_cache(maxsize=1)
def _load_dataset() -> Dict[str, Any]:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Dataset file not found: {DATASET_PATH}")

    xls = pd.ExcelFile(DATASET_PATH)

    # ---------------------------
    # Damage functions (curves)
    # ---------------------------
    damage_df = pd.read_excel(xls, "Damage functions", header=2)
    columns = list(damage_df.columns)
    if len(columns) < 9:
        raise RuntimeError("Unexpected format in 'Damage functions' sheet.")

    damage_df = damage_df.rename(
        columns={columns[0]: "damage_class", columns[1]: "depth_m"}
    )
    damage_df["damage_class"] = damage_df["damage_class"].ffill()
    damage_df["depth_m"] = pd.to_numeric(damage_df["depth_m"], errors="coerce")
    damage_df = damage_df.dropna(subset=["damage_class", "depth_m"])

    func_cols = columns[2:9]  # C-I
    continent_cols = {
        col: _normalize_continent_from_column(str(col)) for col in func_cols
    }

    curves: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    for _, row in damage_df.iterrows():
        asset_raw = str(row["damage_class"]).strip()
        asset_key = _normalize_asset_class(asset_raw)
        if not asset_key:
            continue
        depth_val = _as_float(row["depth_m"])
        if depth_val is None:
            continue
        for col in func_cols:
            cont_key = continent_cols.get(col)
            if not cont_key:
                continue
            value = _as_float(row.get(col))
            if value is None:
                continue
            curves.setdefault(asset_key, {}).setdefault(cont_key, []).append(
                (depth_val, value)
            )

    for asset in curves:
        for cont in curves[asset]:
            curves[asset][cont] = sorted(curves[asset][cont], key=lambda x: x[0])

    # ---------------------------
    # ISO lookup table
    # ---------------------------
    iso_df = pd.read_excel(xls, "ISO_Table")
    iso_map: Dict[str, str] = {}
    for _, row in iso_df.iterrows():
        country = str(row.get("Country") or "").strip()
        if not country:
            continue
        iso2 = str(row.get("A 2") or "").strip()
        iso3 = str(row.get("A 3") or "").strip()
        iso_map[_normalize_country(country)] = country
        if iso2:
            iso_map[_normalize_country(iso2)] = country
        if iso3:
            iso_map[_normalize_country(iso3)] = country

    # ---------------------------
    # Max damage tables
    # ---------------------------
    def _load_building_sheet(sheet_name: str) -> Dict[str, Dict[str, Optional[float]]]:
        df = pd.read_excel(xls, sheet_name, header=1)
        df = df[df.iloc[:, 0].notna()]
        data: Dict[str, Dict[str, Optional[float]]] = {}
        for _, row in df.iterrows():
            country = str(row.iloc[0]).strip()
            if not country:
                continue
            values = {
                "structure": _as_float(row.iloc[1]),
                "content": _as_float(row.iloc[2]),
                "building_total": _as_float(row.iloc[3]),
                "land_use_total": _as_float(row.iloc[4]),
                "object_total": _as_float(row.iloc[5]),
            }
            data[_normalize_country(country)] = values
        return data

    max_damage: Dict[str, Dict[str, Any]] = {
        "residential": _load_building_sheet("MaxDamage-Residential"),
        "commercial": _load_building_sheet("MaxDamage-Commercial"),
        "industrial": _load_building_sheet("MaxDamage-Industrial"),
    }

    # Agriculture (EUR/ha, 2010)
    ag_df = pd.read_excel(xls, "MaxDamage-Agriculture", header=None, skiprows=2)
    ag_data: Dict[str, Dict[str, Optional[float]]] = {}
    for _, row in ag_df.iterrows():
        country = str(row.iloc[0]).strip()
        if not country:
            continue
        ag_data[_normalize_country(country)] = {
            "value_per_hectare": _as_float(row.iloc[1]),
            "area_km2": _as_float(row.iloc[2]),
        }
    max_damage["agriculture"] = ag_data

    # Infrastructure / Transport (Euro/m2 in column I)
    def _load_infra_sheet(sheet_name: str) -> Dict[str, Dict[str, Optional[float]]]:
        df = pd.read_excel(xls, sheet_name, header=1)
        data: Dict[str, Dict[str, Optional[float]]] = {}
        for _, row in df.iterrows():
            country = str(row.iloc[0]).strip()
            if not country:
                continue
            value = _as_float(row.iloc[8]) if len(row) > 8 else None
            if value is None:
                continue
            data[_normalize_country(country)] = {"max_damage": value}
        return data

    max_damage["infrastructure"] = _load_infra_sheet("MaxDamage-Infrastructure")
    max_damage["transport"] = _load_infra_sheet("MaxDamage-Transport")

    return {
        "curves": curves,
        "max_damage": max_damage,
        "iso_map": iso_map,
    }


def _resolve_country_name(country: str, iso_map: Dict[str, str]) -> Optional[str]:
    if not country:
        return None
    normalized = _normalize_country(country)
    return iso_map.get(normalized) or country.strip()


@mcp.tool()
def flood_depth_damage_tool(
    country: str,
    depth_m: float,
    asset_class: Optional[str] = None,
    building_type: Optional[str] = None,
    continent: Optional[str] = None,
    basis: Optional[str] = None,
    year: Optional[int] = None,
) -> ToolResponse:
    """
    Estimate flood damage using global depth-damage curves.

    Args:
        country: Country name or ISO code.
        depth_m: Flood depth in meters (0-6).
        asset_class: Residential, Commercial, Industrial, Agriculture, Infrastructure, Transport.
        building_type: Alias for asset_class (legacy input).
        continent: Optional continent to select the curve (e.g., "Europe", "Asia").
        basis: Optional basis for max damage (building, structure, content, land_use, object).
        year: Year used to apply global multiplier (defaults to current year).
    """
    if not isinstance(country, str) or not country.strip():
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message="Please provide a country name or ISO code.",
            country=country,
            error=True,
        )
    if (not isinstance(asset_class, str) or not asset_class.strip()) and (
        not isinstance(building_type, str) or not building_type.strip()
    ):
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message="Please provide an asset class (e.g., Residential, Commercial).",
            country=country,
            error=True,
        )

    try:
        depth_val = float(depth_m)
    except Exception:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message="Depth must be a numeric value in meters.",
            country=country,
            error=True,
        )

    try:
        resolved_year = _resolve_year(year)
    except Exception as exc:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=str(exc),
            country=country,
            error=True,
        )

    multiplier = GLOBAL_MULTIPLIER.get(resolved_year)
    if multiplier is None:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=(
                "Unsupported year. Provide a year between "
                f"{min(GLOBAL_MULTIPLIER)} and {max(GLOBAL_MULTIPLIER)}."
            ),
            country=country,
            error=True,
        )

    asset_value = (
        asset_class
        if isinstance(asset_class, str) and asset_class.strip()
        else building_type
    )
    asset_key = _normalize_asset_class(asset_value or "")
    if not asset_key:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=f"Unsupported asset class '{asset_value}'.",
            country=country,
            error=True,
        )

    cont_key = _normalize_continent(continent) if continent else None
    basis_key = BASIS_ALIASES.get(_normalize_text(basis)) if basis else None
    if (
        basis
        and basis_key is None
        and asset_key
        in {
            "residential",
            "commercial",
            "industrial",
        }
    ):
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=(
                "Unsupported basis. Use one of: building, structure, content, land_use, object."
            ),
            country=country,
            error=True,
        )
    if basis and asset_key == "agriculture":
        if _normalize_text(basis) not in AG_BASIS_OPTIONS:
            return ToolResponse(
                tool_name="flood_depth_damage_tool",
                message="Unsupported basis for agriculture. Use per_hectare.",
                country=country,
                error=True,
            )
    if basis and asset_key in {"infrastructure", "transport"}:
        if _normalize_text(basis) not in AREA_BASIS_OPTIONS:
            return ToolResponse(
                tool_name="flood_depth_damage_tool",
                message="Unsupported basis. Use per_m2 for infrastructure/transport.",
                country=country,
                error=True,
            )

    try:
        dataset = _load_dataset()
    except Exception as exc:
        logger.error("Failed to load depth-damage dataset.", exc_info=True)
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=f"Failed to load dataset: {exc}",
            country=country,
            error=True,
        )

    curves = dataset["curves"]
    iso_map = dataset["iso_map"]
    max_damage = dataset["max_damage"]

    curve_set = curves.get(asset_key, {})
    if not curve_set:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=f"No damage curves found for asset class '{asset_value}'.",
            country=country,
            error=True,
        )

    selected_continent = cont_key or "global"
    curve = curve_set.get(selected_continent)
    if not curve and cont_key is None:
        # Try global fallback, then fail with guidance
        curve = curve_set.get("global")
    if not curve:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=(
                "No damage curve available for the requested continent. "
                "Provide a continent like Europe, Asia, Africa, Oceania, "
                "North America, or Central/South America."
            ),
            country=country,
            error=True,
        )

    try:
        fractional_damage = _interpolate_damage(depth_val, curve)
    except Exception as exc:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=str(exc),
            country=country,
            error=True,
        )

    resolved_country = _resolve_country_name(country, iso_map)
    max_table = max_damage.get(asset_key, {})
    max_values = max_table.get(_normalize_country(resolved_country or country))
    if not max_values:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message=f"No max damage values found for {country} ({asset_class}).",
            country=country,
            error=True,
        )

    max_value = None
    unit = None
    basis_used = None
    extra_values = {}

    if asset_key in {"residential", "commercial", "industrial"}:
        basis_used = basis_key or "building_total"
        max_value = max_values.get(basis_used)
        extra_values = max_values
        unit = "EUR/m2"
    elif asset_key == "agriculture":
        basis_used = "per_hectare"
        max_value = max_values.get("value_per_hectare")
        extra_values = max_values
        unit = "EUR/ha"
    else:
        basis_used = "per_m2"
        max_value = max_values.get("max_damage")
        extra_values = max_values
        unit = "EUR/m2"

    if max_value is None:
        return ToolResponse(
            tool_name="flood_depth_damage_tool",
            message="Max damage value is missing for the selected basis.",
            country=country,
            error=True,
        )

    adjusted_max_value = max_value * multiplier
    estimated_damage = fractional_damage * adjusted_max_value

    message = (
        f"Estimated flood damage for {asset_key} in {resolved_country}: "
        f"{fractional_damage:.3f} fraction at {depth_val} m depth. "
        f"Max damage ({basis_used}) is {adjusted_max_value:.2f} {unit} "
        f"(year {resolved_year}, multiplier {multiplier:.3f}), "
        f"estimated damage ~ {estimated_damage:.2f} {unit}."
    )

    return ToolResponse(
        tool_name="flood_depth_damage_tool",
        message=message,
        country=resolved_country,
        data={
            "asset_class": asset_key,
            "continent": selected_continent,
            "depth_m": depth_val,
            "fractional_damage": fractional_damage,
            "basis": basis_used,
            "adjusted_max_damage_value": adjusted_max_value,
            "estimated_damage": estimated_damage,
            "unit": unit,
        },
        error=False,
    )
