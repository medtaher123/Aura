"""
Services module - Contains business logic services like agent, translation, and extraction
"""

from .translate_service import (
    detect_language,
    translate_to_english,
    translate_from_english,
    detect_and_translate_to_english,
)
from .llm_service import get_llm

__all__ = [
    "detect_language",
    "translate_to_english",
    "translate_from_english",
    "detect_and_translate_to_english",
    "get_llm",
]
