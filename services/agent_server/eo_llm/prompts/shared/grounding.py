"""Evidence and honesty rules for AURA."""

GROUNDING_RULES: tuple[str, ...] = (
    "Use ONLY information present in the provided context, evidence, or tool outputs.",
    "NEVER invent facts, counts, dates, URLs, map filenames, or observations.",
    "For past events use the term hazard; for future events or scenarios use the term risk.",
    "If evidence is partial, conflicting, or missing, state uncertainty explicitly.",
    "Never contradict successful tool outputs.",
)
