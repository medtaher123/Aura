"""Tests for live tool progress argument cleanup helpers."""

from __future__ import annotations

from pathlib import Path


def _load_arguments_helper():
    """Load ``_tool_arguments_from_event`` without importing the full Streamlit app."""
    path = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    source = path.read_text(encoding="utf-8")
    start = source.index("def _tool_arguments_from_event")
    end = source.index("\ndef _tool_call_key", start)
    snippet = source[start:end]
    namespace: dict = {}
    exec(snippet, namespace)
    return namespace["_tool_arguments_from_event"]


def test_tool_arguments_strips_step_metadata():
    helper = _load_arguments_helper()
    cleaned = helper(
        {
            "tool_input": {
                "location_query": "Pas-de-Calais, France",
                "step_id": "s1",
                "domain": "flood_damage",
            }
        }
    )
    assert cleaned == {"location_query": "Pas-de-Calais, France"}


def test_tool_arguments_accepts_arguments_key():
    helper = _load_arguments_helper()
    cleaned = helper({"arguments": {"lat": 48.0, "lon": 2.0}})
    assert cleaned == {"lat": 48.0, "lon": 2.0}


def test_tool_arguments_returns_none_when_missing():
    helper = _load_arguments_helper()
    assert helper({"phase": "running"}) is None
