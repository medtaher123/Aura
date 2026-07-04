"""STAC / imagery domain tool selection rules."""

STAC_TOOL_RULES: tuple[str, ...] = (
    "Use query_stac_catalog for Sentinel/STAC catalog search, thumbnails, and generic satellite imagery by place and date.",
    "Use maxar_open_data_imagery_tool for Maxar open disaster imagery by COUNTRY and YEAR (optionally month).",
    "Do NOT use maxar_open_data_imagery_tool for fires (use fire_detection) or for generic Sentinel catalog search.",
    "Do NOT use STAC tools for hydrological forecasts or streamflow; those belong in flood_damage.",
)

STAC_EXAMPLES: tuple[str, ...] = (
    "Query: Sentinel-2 images of Casablanca September 2025\n"
    "Plan: 1 step — query_stac_catalog.",
    "Query: Maxar imagery for Brazil 2024\n"
    "Plan: 1 step — maxar_open_data_imagery_tool.",
)
