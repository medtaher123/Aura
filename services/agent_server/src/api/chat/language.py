"""Inbound message language helpers for the chat WebSocket path."""

from __future__ import annotations

from src.services.translate_service import detect_and_translate_to_english


def to_english(text: str, language: str | None) -> tuple[str, str]:
    """Return ``(english_text, language_code)`` for LLM / persistence.

    If ``language`` is already ``\"en\"``, skip detection. Otherwise detect and
    translate when needed.
    """
    if language == "en":
        return text, "en"
    english, detected = detect_and_translate_to_english(text)
    return english, language or detected
