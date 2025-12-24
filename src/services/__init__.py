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


def create_agent_executor():
    # Lazy import to avoid circular imports when tools import submodules from src.services.
    from .agent_service import create_agent_executor as _create_agent_executor

    return _create_agent_executor()

__all__ = [
    "detect_language",
    "translate_to_english",
    "translate_from_english",
    "detect_and_translate_to_english",
    "create_agent_executor",
    "get_llm",
]
