"""Cursor-style multiple-choice card (custom component, no full-page reload)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from src.ui.multiple_choice_input import (
    OTHER_OPTION_ID,
    choice_labels_from_payload,
)

_MC_PICKER = components.declare_component(
    "mc_picker",
    path=str(Path(__file__).resolve().parent / "mc_picker"),
)


@dataclass(frozen=True)
class MultipleChoiceUIResult:
    option_id: str | None
    option_label: str | None
    custom_text: str | None
    submitted: bool


def _inject_shell_styles() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stVerticalBlockBorderWrapper"]:has(.mc-root) {
            width: 100%;
            max-width: 100%;
        }
        iframe[data-testid="stIFrame"] {
            width: 100% !important;
            max-width: 100% !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def _value_key(prefix: str) -> str:
    return f"{prefix}_value"


def _picker_key(prefix: str) -> str:
    return f"{prefix}_picker"


def _option_letter(index: int) -> str:
    if index < 26:
        return chr(ord("A") + index)
    return chr(ord("A") + (index % 26))


def _selection_dict(
    *,
    option_id: str,
    option_label: str,
    custom_text: str | None = None,
) -> dict[str, Any]:
    return {
        "option_id": option_id,
        "option_label": option_label,
        "custom_text": custom_text,
    }


def _estimate_card_height(choice_count: int, *, allow_other: bool) -> int:
    base = 130 + (choice_count * 54)
    return base + (72 if allow_other else 0)


def _parse_picker_value(picked: Any) -> tuple[str | None, str]:
    if isinstance(picked, dict):
        option_id = picked.get("option_id")
        custom_text = str(picked.get("custom_text") or "")
        return (str(option_id) if option_id else None, custom_text)
    if isinstance(picked, str) and picked:
        return picked, ""
    return None, ""


def _sync_selection_from_picker(
    *,
    picked: Any,
    choices: list[tuple[str, str]],
    value_key: str,
    other_label: str,
) -> tuple[str | None, str, bool]:
    """Apply picker widget value to session state; return display args for component."""
    choice_ids = {option_id for option_id, _ in choices}
    label_map = dict(choices)
    option_id, other_text = _parse_picker_value(picked)

    if option_id == OTHER_OPTION_ID:
        st.session_state[value_key] = _selection_dict(
            option_id=OTHER_OPTION_ID,
            option_label=other_text.strip() or other_label,
            custom_text=other_text,
        )
        return None, other_text, True

    if option_id in choice_ids:
        st.session_state[value_key] = _selection_dict(
            option_id=option_id,
            option_label=label_map[option_id],
        )
        return option_id, "", False

    if choices:
        fallback_id = choices[0][0]
        st.session_state[value_key] = _selection_dict(
            option_id=fallback_id,
            option_label=label_map[fallback_id],
        )
        return fallback_id, "", False

    return None, "", False


def render_multiple_choice_ui(
    payload: dict[str, Any],
    *,
    key_prefix: str | None = None,
) -> MultipleChoiceUIResult:
    """Render a Cursor-style question card. Returns selection + external submit flag."""
    prompt = str(payload.get("prompt") or "Select an option")
    choices = choice_labels_from_payload(payload)
    allow_other = bool(payload.get("allow_other", True))
    other_label = str(payload.get("other_label") or "Other")

    prefix = key_prefix or f"user_input_mc_{_payload_fingerprint(payload)}"
    value_key = _value_key(prefix)
    picker_key = _picker_key(prefix)

    picked = st.session_state.get(picker_key)
    if picked is None and choices:
        picked = choices[0][0]

    display_selected, other_text, other_selected = _sync_selection_from_picker(
        picked=picked,
        choices=choices,
        value_key=value_key,
        other_label=other_label,
    )

    option_payload = [
        {
            "id": option_id,
            "label": label,
            "letter": _option_letter(index),
        }
        for index, (option_id, label) in enumerate(choices)
    ]

    _inject_shell_styles()

    with st.container(border=True):
        st.markdown('<span class="mc-root" aria-hidden="true"></span>', unsafe_allow_html=True)
        _MC_PICKER(
            prompt=prompt,
            options=option_payload,
            selected_id=display_selected,
            allow_other=allow_other,
            other_label=other_label,
            other_letter=_option_letter(len(choices)),
            other_option_id=OTHER_OPTION_ID,
            other_text=other_text,
            other_selected=other_selected,
            key=picker_key,
            default=picked if picked is not None else (choices[0][0] if choices else None),
            height=_estimate_card_height(len(choices), allow_other=allow_other),
        )

    val = st.session_state.get(value_key) if isinstance(st.session_state.get(value_key), dict) else {}
    selected_id = val.get("option_id")
    option_label = val.get("option_label")
    custom_text = val.get("custom_text")

    submitted = st.button(
        "Continue",
        type="primary",
        key=f"{prefix}_continue",
        use_container_width=True,
    )

    return MultipleChoiceUIResult(
        option_id=str(selected_id) if selected_id else None,
        option_label=str(option_label) if option_label else None,
        custom_text=str(custom_text).strip() if custom_text else None,
        submitted=submitted,
    )
