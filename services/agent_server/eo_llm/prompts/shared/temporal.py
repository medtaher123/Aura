"""Date and time inference rules."""

TEMPORAL_RULES: tuple[str, ...] = (
    "Format dates as YYYY-MM-DD unless the tool schema requires another format.",
    "Resolve relative periods from the user query (e.g. last summer, last month, January 2025, in 2024).",
    "When the query specifies a time period, OVERRIDE candidate/default date values to match the query.",
    "Only keep default date values when the query has no temporal reference.",
    "Never claim a date is in the future unless it is strictly later than today's date (UTC).",
)
