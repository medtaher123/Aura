# translate.py
import re
from typing import Optional
from langdetect import detect
from deep_translator import GoogleTranslator
from src.core.logger import get_logger



logger = get_logger(__name__)


# Détection de la  langue
def detect_language(text: str) -> str:
    try:
        logger.debug(f"Detecting language for text: {text[:50]}...")
        lang = detect(text)
        # Langues courantes gérées automatiquement
        common = {
            "ar",
            "fr",
            "en",
            "es",
            "de",
            "it",
            "pt",
            "tr",
            "zh-cn",
            "zh-tw",
            "ja",
            "ko",
            "ru",
        }
        result = lang if lang in common else "en"
        logger.info(f"Detected language: {lang} -> using: {result}")
        return result
    except Exception as e:
        logger.warning(
            f"Language detection failed: {type(e).__name__}: {str(e)}, defaulting to 'en'"
        )
        return "en"


# Protection des éléments techniques avant traduction
def protect(text: str) -> str:
    """
    Empêche la traduction des blocs techniques :
    - fichiers .html .csv .png .jpg
    - URLs
    - JSON / dict / []
    - bbox
    - coordonnées
    - identifiants Sentinel / STAC / MODIS / VIIRS
    - chaînes contenant underscores
    - dates ISO
    """
    # fichiers
    text = re.sub(
        r"(\b[\w\-]+\.(?:html?|csv|png|jpg|jpeg|tif|json)\b)",
        r"<PROTECT>\1</PROTECT>",
        text,
    )

    # URLs
    text = re.sub(r"(https?://[^\s]+)", r"<PROTECT>\1</PROTECT>", text)

    # JSON {…} ou […]
    text = re.sub(r"(\{.*?\}|\[.*?\])", r"<PROTECT>\1</PROTECT>", text)

    # bbox
    text = re.sub(
        r"(-?\d+\.\d+,-?\d+\.\d+,-?\d+\.\d+,-?\d+\.\d+)", r"<PROTECT>\1</PROTECT>", text
    )

    # coordonnées simples
    text = re.sub(r"(-?\d+\.\d+,\s*-?\d+\.\d+)", r"<PROTECT>\1</PROTECT>", text)

    # éléments avec underscores (ex: fire_archive_2020_2021.csv)
    text = re.sub(r"(\b[\w\-]+_[\w\-]+\b)", r"<PROTECT>\1</PROTECT>", text)

    # dates ISO
    text = re.sub(r"(\b\d{4}-\d{2}-\d{2}\b)", r"<PROTECT>\1</PROTECT>", text)

    # mots-clés techniques
    keywords = [
        r"sentinel-1",
        r"sentinel-2",
        r"modis",
        r"viirs",
        r"firms",
        r"bbox",
        r"stac",
        r"nrt",
        r"grd",
        r"l2a",
        r"viirs-noaa20",
    ]

    for kw in keywords:
        text = re.sub(
            rf"(\b{kw}\b)", r"<PROTECT>\1</PROTECT>", text, flags=re.IGNORECASE
        )

    return text


# Dé-protection après traduction
def unprotect(text: str) -> str:
    return text.replace("<PROTECT>", "").replace("</PROTECT>", "")


#   Traduction → anglais (input vers agent)
def translate_to_english(text: str) -> str:
    try:
        logger.debug(f"Translating to English: {text[:100]}...")
        safe = protect(text)
        translated = GoogleTranslator(source="auto", target="en").translate(safe)
        result = unprotect(translated)
        logger.info(
            f"Translation to English successful: {len(text)} chars -> {len(result)} chars"
        )
        return result
    except Exception as e:
        logger.error(
            f"Translation to English failed: {type(e).__name__}: {str(e)}, returning original text"
        )
        return text


def translate_from_english(text: str, target_lang: Optional[str] = None) -> str:
    try:
        if target_lang == "en" or not target_lang:
            logger.debug("Target language is English or None, skipping translation")
            return text

        logger.debug(f"Translating from English to {target_lang}: {text[:100]}...")
        # Reuse protection logic to keep file names, paths, URLs, and technical tokens unchanged
        safe_text = protect(text)

        translated = GoogleTranslator(source="auto", target=target_lang).translate(
            safe_text
        )
        result = unprotect(translated)
        logger.info(
            f"Translation from English to {target_lang} successful: {len(text)} chars -> {len(result)} chars"
        )

        return result

    except Exception as e:
        logger.error(
            f"Translation from English to {target_lang} failed: {type(e).__name__}: {str(e)}, returning original text"
        )
        return text


# Pipeline : détecter + traduire vers anglais
def detect_and_translate_to_english(text: str):
    logger.debug("Starting detect and translate pipeline")
    lang = detect_language(text)
    if lang == "en":
        logger.info("Text is already in English, no translation needed")
        return text, lang
    logger.info(f"Text is in {lang}, translating to English")
    translated = translate_to_english(text)
    return translated, lang
