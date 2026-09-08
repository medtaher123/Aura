"""Structured JSON output rules for Bedrock schema-constrained calls."""

SCHEMA_OUTPUT_RULES: tuple[str, ...] = (
    "Return ONLY data that conforms to the provided JSON schema.",
    "Do not include markdown, backticks, explanations, or extra keys.",
    "Follow the schema exactly.",
)
