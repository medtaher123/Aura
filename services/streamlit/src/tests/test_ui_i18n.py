"""
Tests for ui/i18n.py - Internationalization labels.
"""

import pytest

from ui import get_labels, LABELS


class TestGetLabels:
    """Tests for get_labels function."""

    def test_english_labels(self):
        labels = get_labels("en")
        assert labels["results_for"] == "Results for collection"
        assert labels["cloud"] == "Cloud"
        assert labels["date"] == "Date"

    def test_french_labels(self):
        labels = get_labels("fr")
        assert labels["results_for"] == "Results for collection"
        assert labels["cloud"] == "Cloud"
        assert labels["date"] == "Date"

    def test_spanish_labels(self):
        labels = get_labels("es")
        assert labels["results_for"] == "Resultados para la colección"
        assert labels["cloud"] == "Nube"
        assert labels["date"] == "Fecha"

    def test_arabic_labels(self):
        labels = get_labels("ar")
        assert labels["results_for"] == "نتائج المجموعة"
        assert labels["cloud"] == "السحب"
        assert labels["date"] == "التاريخ"

    def test_italian_labels(self):
        labels = get_labels("it")
        assert labels["results_for"] == "Risultati per la collezione"
        assert labels["cloud"] == "Nuvolosità"
        assert labels["date"] == "Data"

    def test_german_labels(self):
        labels = get_labels("de")
        assert labels["results_for"] == "Ergebnisse für die Sammlung"
        assert labels["cloud"] == "Wolken"
        assert labels["date"] == "Datum"

    def test_unknown_language_fallback_to_english(self):
        labels = get_labels("unknown")
        assert labels == LABELS["en"]

    def test_empty_language_fallback_to_english(self):
        labels = get_labels("")
        assert labels == LABELS["en"]

    def test_none_language_fallback_to_english(self):
        labels = get_labels(None)
        assert labels == LABELS["en"]

    def test_language_with_region_code(self):
        """Test that language codes like 'en-US' or 'fr-FR' work."""
        labels = get_labels("en-US")
        assert labels == LABELS["en"]

        labels = get_labels("fr-FR")
        assert labels == LABELS["fr"]

        labels = get_labels("es-MX")
        assert labels == LABELS["es"]


class TestLabelsStructure:
    """Tests for LABELS dictionary structure."""

    def test_all_languages_have_same_keys(self):
        """Ensure all language dictionaries have the same keys."""
        expected_keys = {"results_for", "cloud", "date"}

        for lang, labels in LABELS.items():
            assert set(labels.keys()) == expected_keys, f"Language {lang} missing keys"

    def test_all_values_are_strings(self):
        """Ensure all label values are non-empty strings."""
        for lang, labels in LABELS.items():
            for key, value in labels.items():
                assert isinstance(value, str), f"{lang}.{key} is not a string"
                assert len(value) > 0, f"{lang}.{key} is empty"

    def test_english_is_fallback(self):
        """Ensure English exists as the fallback."""
        assert "en" in LABELS
