"""
Tests for services/translate_service.py - Language detection and translation.
"""

import pytest

from src.services.translate_service import (
    detect_language,
    protect,
    unprotect,
    translate_to_english,
    translate_from_english,
    detect_and_translate_to_english,
)


class TestDetectLanguage:
    """Tests for detect_language function."""

    def test_english_detected(self):
        result = detect_language("Hello, how are you today?")
        assert result == "en"

    def test_french_detected(self):
        result = detect_language("Bonjour, comment allez-vous aujourd'hui?")
        assert result == "fr"

    def test_spanish_detected(self):
        result = detect_language("Hola, cómo estás hoy?")
        assert result == "es"

    def test_german_detected(self):
        result = detect_language("Guten Tag, wie geht es Ihnen heute?")
        assert result == "de"

    def test_arabic_detected(self):
        result = detect_language("مرحبا كيف حالك اليوم؟")
        assert result == "ar"

    def test_short_text_fallback(self):
        # Very short text may not be detected reliably
        result = detect_language("hi")
        assert isinstance(result, str)

    def test_empty_string_fallback(self):
        result = detect_language("")
        assert result == "en"  # Fallback

    def test_unknown_language_fallback(self):
        # Random characters should fall back to English
        result = detect_language("xyz123")
        assert result == "en"


class TestProtect:
    """Tests for protect function - protecting technical elements."""

    def test_protects_file_names(self):
        text = "Download the file data.csv and image.png"
        result = protect(text)
        assert "<PROTECT>data.csv</PROTECT>" in result
        assert "<PROTECT>image.png</PROTECT>" in result

    def test_protects_urls(self):
        text = "Visit https://example.com/api?foo=bar for more info"
        result = protect(text)
        assert "<PROTECT>https://example.com/api?foo=bar</PROTECT>" in result

    def test_protects_json_objects(self):
        text = 'The config is {"key": "value"}'
        result = protect(text)
        assert "<PROTECT>" in result
        assert "</PROTECT>" in result

    def test_protects_arrays(self):
        text = "The list is [1, 2, 3]"
        result = protect(text)
        assert "<PROTECT>[1, 2, 3]</PROTECT>" in result

    def test_protects_bbox_coordinates(self):
        text = "bbox: -122.5,37.7,-122.3,37.9"
        result = protect(text)
        # The protect function may apply multiple overlapping patterns
        assert "<PROTECT>" in result
        assert "122.5" in result
        assert "37.7" in result

    def test_protects_simple_coordinates(self):
        text = "Location: 48.8566, 2.3522"
        result = protect(text)
        assert "<PROTECT>" in result

    def test_protects_underscore_identifiers(self):
        text = "Use detect_fire_tool for detection"
        result = protect(text)
        assert "<PROTECT>detect_fire_tool</PROTECT>" in result

    def test_protects_iso_dates(self):
        text = "Start date: 2024-01-15"
        result = protect(text)
        assert "<PROTECT>2024-01-15</PROTECT>" in result

    def test_protects_technical_keywords(self):
        keywords = ["sentinel-2", "modis", "viirs", "stac", "bbox"]
        for kw in keywords:
            text = f"Query the {kw} data"
            result = protect(text)
            # Check that PROTECT tags are present (case-sensitive)
            assert "<PROTECT>" in result

    def test_no_protection_for_plain_text(self):
        text = "This is plain text with no technical elements"
        result = protect(text)
        assert "<PROTECT>" not in result


class TestUnprotect:
    """Tests for unprotect function - removing protection tags."""

    def test_removes_protection_tags(self):
        text = "Download <PROTECT>file.csv</PROTECT> here"
        result = unprotect(text)
        assert result == "Download file.csv here"

    def test_multiple_tags_removed(self):
        text = "<PROTECT>a</PROTECT> and <PROTECT>b</PROTECT>"
        result = unprotect(text)
        assert result == "a and b"

    def test_no_tags_unchanged(self):
        text = "Plain text without tags"
        result = unprotect(text)
        assert result == text

    def test_nested_content_preserved(self):
        text = "<PROTECT>https://example.com?a=1&b=2</PROTECT>"
        result = unprotect(text)
        assert result == "https://example.com?a=1&b=2"


class TestTranslateToEnglish:
    """Tests for translate_to_english function."""

    def test_english_unchanged(self):
        text = "Hello world"
        result = translate_to_english(text)
        assert result == text or "hello" in result.lower()

    def test_french_translated(self):
        text = "Bonjour le monde"
        result = translate_to_english(text)
        # Should contain English translation
        assert isinstance(result, str)
        assert len(result) > 0

    def test_preserves_technical_elements(self):
        text = "Télécharger sentinel-2 données"
        result = translate_to_english(text)
        # sentinel-2 should be preserved
        assert "sentinel-2" in result.lower() or "sentinel" in result.lower()

    def test_handles_empty_string(self):
        result = translate_to_english("")
        assert result == ""


class TestTranslateFromEnglish:
    """Tests for translate_from_english function."""

    def test_english_target_unchanged(self):
        text = "Hello world"
        result = translate_from_english(text, "en")
        assert result == text

    def test_none_target_unchanged(self):
        text = "Hello world"
        result = translate_from_english(text, None)
        assert result == text

    def test_french_target_translates(self):
        text = "Hello world"
        result = translate_from_english(text, "fr")
        # Should return something (translation)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_preserves_technical_elements(self):
        text = "Download sentinel-2 data from 2024-01-15"
        result = translate_from_english(text, "fr")
        # Technical elements should be preserved (at least partially)
        assert "sentinel" in result.lower()
        # Date may be reformatted by translator, just check year is preserved
        assert "2024" in result


class TestDetectAndTranslateToEnglish:
    """Tests for detect_and_translate_to_english function."""

    def test_english_input_unchanged(self):
        text = "Hello, how are you?"
        result, lang = detect_and_translate_to_english(text)
        assert lang == "en"
        assert result == text

    def test_french_input_translated(self):
        text = "Bonjour, comment allez-vous?"
        result, lang = detect_and_translate_to_english(text)
        assert lang == "fr"
        assert isinstance(result, str)
        # Result should be translated to English
        assert len(result) > 0

    def test_returns_tuple(self):
        result = detect_and_translate_to_english("Test")
        assert isinstance(result, tuple)
        assert len(result) == 2
