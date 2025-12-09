# translate.py
import re
from langdetect import detect
from deep_translator import GoogleTranslator
from langchain.tools import tool


# Détection de la  langue
def detect_language(text: str) -> str:
    try:
        lang = detect(text)
        # Langues courantes gérées automatiquement
        common = {
            "ar", "fr", "en", "es", "de", "it", "pt",
            "tr", "zh-cn", "zh-tw", "ja", "ko", "ru"
        }
        return lang if lang in common else "en"
    except:
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
        r"<PROTECT>\1</PROTECT>", text
    )

    # URLs
    text = re.sub(
        r"(https?://[^\s]+)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # JSON {…} ou […]
    text = re.sub(
        r"(\{.*?\}|\[.*?\])",
        r"<PROTECT>\1</PROTECT>", text
    )

    # bbox
    text = re.sub(
        r"(-?\d+\.\d+,-?\d+\.\d+,-?\d+\.\d+,-?\d+\.\d+)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # coordonnées simples
    text = re.sub(
        r"(-?\d+\.\d+,\s*-?\d+\.\d+)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # éléments avec underscores (ex: fire_archive_2020_2021.csv)
    text = re.sub(
        r"(\b[\w\-]+_[\w\-]+\b)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # dates ISO
    text = re.sub(
        r"(\b\d{4}-\d{2}-\d{2}\b)",
        r"<PROTECT>\1</PROTECT>", text
    )

    # mots-clés techniques
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


#Dé-protection après traduction
def unprotect(text: str) -> str:
    return text.replace("<PROTECT>", "").replace("</PROTECT>", "")



#   Traduction → anglais (input vers agent)
def translate_to_english(text: str) -> str:
    try:
        safe = protect(text)
        translated = GoogleTranslator(source="auto", target="en").translate(safe)
        return unprotect(translated)
    except:
        return text


def translate_from_english(text: str, target_lang: str=None) -> str:
    try:
        if target_lang == "en" or not target_lang:
            return text

        # Detect URLs and file paths
        urls = re.findall(r'https?://\S+|www\.\S+', text)
        paths = re.findall(r'([a-zA-Z]:\\[^\s]+|/[\w/.-]+\.html|/[\w/.-]+)', text)

        # Combine all protected segments
        protected_segments = urls + paths
        placeholders = {f"__PLACEHOLDER_{i}__": seg for i, seg in enumerate(protected_segments)}

        # Replace them in the text
        safe_text = text
        for ph, seg in placeholders.items():
            safe_text = safe_text.replace(seg, ph)

        # Translate the rest
        translated = GoogleTranslator(source="auto", target=target_lang).translate(safe_text)

        # Restore the placeholders
        for ph, seg in placeholders.items():
            translated = translated.replace(ph, seg)

        return translated

    except Exception as e:
        print(f"Translation error: {e}")
        return text



# Pipeline : détecter + traduire vers anglais
def detect_and_translate_to_english(text: str):
    lang = detect_language(text)
    if lang == "en":
        return text, lang
    return translate_to_english(text), lang
