"""Services package.

Keep this module lightweight.

Some services depend on optional heavy libraries (LLM backends, translators, etc).
Importing them here at module import time makes unrelated tools fail to import.

Expose a stable API via lazy wrappers instead.
"""


def detect_language(text: str):
    from .translate_service import detect_language as _impl

    return _impl(text)


def translate_to_english(text: str):
    from .translate_service import translate_to_english as _impl

    return _impl(text)


def translate_from_english(text: str, target_lang: str):
    from .translate_service import translate_from_english as _impl

    return _impl(text, target_lang)


def detect_and_translate_to_english(text: str):
    from .translate_service import detect_and_translate_to_english as _impl

    return _impl(text)


def get_llm(*args, **kwargs):
    from .llm_service import get_llm as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "detect_language",
    "translate_to_english",
    "translate_from_english",
    "detect_and_translate_to_english",
    "get_llm",
]
