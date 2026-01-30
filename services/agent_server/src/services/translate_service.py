"""Translation service module.

Handles language detection and translation between user's language and English.
"""

import re
from langdetect import detect
from deep_translator import GoogleTranslator

from ..core.logger import get_logger

logger = get_logger("translate")


def detect_language(text: str) -> str:
    """Detect the language of the input text."""
    try:
        lang = detect(text)
        # Common languages handled automatically
        common = {
            "ar", "fr", "en", "es", "de", "it", "pt",
            "tr", "zh-cn", "zh-tw", "ja", "ko", "ru"
        }
        return lang if lang in common else "en"
    except Exception:
        return "en"


def protect(text: str) -> str:
    """
    Protect technical elements from translation:
    - file names (.html, .csv, .png, .jpg)
    - URLs
    - JSON / dict / []
    - bbox
    - coordinates
    - Sentinel / STAC / MODIS / VIIRS identifiers
    - strings containing underscores
    - ISO dates
    """
    # Files
    text = re.sub(
        r"(\b[\w\-]+\.(?:html?|csv|png|jpg|jpeg|tif|json)\b)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # URLs
    text = re.sub(
        r"(https?://[^\s]+)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # JSON {…} or […]
    text = re.sub(
        r"(\{.*?\}|\[.*?\])",
        r"<PROTECT>\1</PROTECT>", text
    )

    # bbox
    text = re.sub(
        r"(-?\d+\.\d+,-?\d+\.\d+,-?\d+\.\d+,-?\d+\.\d+)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # Simple coordinates
    text = re.sub(
        r"(-?\d+\.\d+,\s*-?\d+\.\d+)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # Elements with underscores (e.g., fire_archive_2020_2021.csv)
    text = re.sub(
        r"(\b[\w\-]+_[\w\-]+\b)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # ISO dates
    text = re.sub(
        r"(\b\d{4}-\d{2}-\d{2}\b)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # Technical keywords
    keywords = [
        r"sentinel-1", r"sentinel-2", r"modis", r"viirs", r"firms",
        r"bbox", r"stac", r"nrt", r"grd", r"l2a", r"viirs-noaa20"
    ]

    for kw in keywords:
        text = re.sub(
            rf"(\b{kw}\b)", r"<PROTECT>\1</PROTECT>",
            text, flags=re.IGNORECASE
        )

    return text


def unprotect(text: str) -> str:
    """Remove protection markers after translation."""
    return text.replace("<PROTECT>", "").replace("</PROTECT>", "")


def translate_to_english(text: str) -> str:
    """Translate text to English."""
    try:
        safe = protect(text)
        translated = GoogleTranslator(source="auto", target="en").translate(safe)
        return unprotect(translated)
    except Exception:
        return text


def translate_from_english(text: str, target_lang: str = None) -> str:
    """Translate text from English to target language."""
    try:
        if target_lang == "en" or not target_lang:
            return text
        # Reuse protection logic to keep file names, paths, URLs, and technical tokens unchanged
        safe_text = protect(text)

        translated = GoogleTranslator(source="auto", target=target_lang).translate(safe_text)

        return unprotect(translated)

    except Exception as e:
        logger.error(f"Translation failed from English to {target_lang}: {e}", exc_info=True)
        return text


def detect_and_translate_to_english(text: str):
    """Detect language and translate to English if needed.
    
    Returns:
        Tuple of (translated_text, detected_language)
    """
    lang = detect_language(text)
    if lang == "en":
        return text, lang
    return translate_to_english(text), lang
