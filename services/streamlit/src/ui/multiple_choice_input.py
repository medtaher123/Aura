"""Helpers for multiple-choice user-input attachments."""

from __future__ import annotations

from typing import Any

OTHER_OPTION_ID = "__other__"


def multiple_choice_attachment(
    *,
    option_id: str,
    label: str,
    custom_text: str | None = None,
    prompt: str | None = None,
    offered_options: list[dict[str, str]] | None = None,
    allow_other: bool = True,
    other_label: str = "Other",
) -> dict[str, Any]:
    """Build a ``type=multiple_choice`` attachment for chat_resume."""
    payload: dict[str, Any] = {
        "type": "multiple_choice",
        "option_id": str(option_id),
        "label": str(label).strip(),
        "allow_other": bool(allow_other),
        "other_label": str(other_label or "Other"),
    }
    if prompt is not None and str(prompt).strip():
        payload["prompt"] = str(prompt).strip()
    if offered_options:
        payload["offered_options"] = [
            {"id": str(item["id"]), "label": str(item["label"]).strip()}
            for item in offered_options
            if isinstance(item, dict) and item.get("id") and item.get("label")
        ]
    if custom_text is not None and str(custom_text).strip():
        payload["custom_text"] = str(custom_text).strip()
    return payload


def choice_labels_from_payload(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ``(option_id, label)`` pairs from a needs_input multiple_choice payload."""
    out: list[tuple[str, str]] = []
    for item in payload.get("options") or []:
        if not isinstance(item, dict):
            continue
        option_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        if option_id and label:
            out.append((option_id, label))
    return out


def offered_options_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Return ``[{id, label}, ...]`` for attachment context."""
    return [{"id": option_id, "label": label} for option_id, label in choice_labels_from_payload(payload)]
