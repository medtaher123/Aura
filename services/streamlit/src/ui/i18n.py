from __future__ import annotations

from typing import Dict


# MULTILINGUAL LABELS (English defaults)
LABELS: Dict[str, Dict[str, str]] = {
    "fr": {"results_for": "Results for collection", "cloud": "Cloud", "date": "Date"},
    "en": {"results_for": "Results for collection", "cloud": "Cloud", "date": "Date"},
    "es": {"results_for": "Resultados para la colección", "cloud": "Nube", "date": "Fecha"},
    "ar": {"results_for": "نتائج المجموعة", "cloud": "السحب", "date": "التاريخ"},
    "it": {"results_for": "Risultati per la collezione", "cloud": "Nuvolosità", "date": "Data"},
    "de": {"results_for": "Ergebnisse für die Sammlung", "cloud": "Wolken", "date": "Datum"},
}


def get_labels(lang_code: str | None) -> Dict[str, str]:
    base = lang_code.split("-")[0] if lang_code else "en"
    return LABELS.get(base, LABELS["en"])
