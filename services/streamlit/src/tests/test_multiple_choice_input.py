"""Tests for Streamlit multiple-choice attach helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "ui" / "multiple_choice_input.py"
_SPEC = importlib.util.spec_from_file_location("multiple_choice_input", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_mod)

OTHER_OPTION_ID = _mod.OTHER_OPTION_ID
choice_labels_from_payload = _mod.choice_labels_from_payload
multiple_choice_attachment = _mod.multiple_choice_attachment
offered_options_from_payload = _mod.offered_options_from_payload


def test_multiple_choice_attachment_payload():
    payload = multiple_choice_attachment(
        option_id="flood",
        label="Flood depth",
    )
    assert payload["type"] == "multiple_choice"
    assert payload["option_id"] == "flood"
    assert payload["label"] == "Flood depth"
    assert "custom_text" not in payload


def test_multiple_choice_attachment_other():
    payload = multiple_choice_attachment(
        option_id=OTHER_OPTION_ID,
        label="Other",
        custom_text="My custom answer",
    )
    assert payload["custom_text"] == "My custom answer"


def test_choice_labels_from_payload():
    labels = choice_labels_from_payload(
        {
            "options": [
                {"id": "a", "label": "Alpha"},
                {"id": "b", "label": "Beta"},
            ],
            "allow_other": True,
        }
    )
    assert labels == [("a", "Alpha"), ("b", "Beta")]


def test_multiple_choice_attachment_includes_context():
    payload = multiple_choice_attachment(
        option_id="flood",
        label="Flood depth",
        prompt="Pick a layer",
        offered_options=[
            {"id": "flood", "label": "Flood depth"},
            {"id": "fire", "label": "Fire perimeter"},
        ],
        allow_other=False,
    )
    assert payload["prompt"] == "Pick a layer"
    assert len(payload["offered_options"]) == 2
    assert payload["allow_other"] is False


def test_offered_options_from_payload():
    options = offered_options_from_payload(
        {
            "options": [
                {"id": "a", "label": "Alpha"},
                {"id": "b", "label": "Beta"},
            ]
        }
    )
    assert options == [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}]
