"""Tests for chronological agent timeline text/tool upserts."""

from __future__ import annotations

from pathlib import Path


def _load_helpers():
    path = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    source = path.read_text(encoding="utf-8")
    start = source.index("def _is_node_progress_event")
    # Include timeline stream helpers; stop before Streamlit-dependent renderers.
    end = source.index("\ndef _render_node_start_lines", start)
    # Also need helpers defined earlier in the file (before _is_node_progress_event).
    early_start = source.index("def _close_open_timeline_text")
    early_end = source.index("\ndef _make_tool_status_tracker", early_start)
    namespace: dict = {"html": __import__("html")}
    exec(source[early_start:early_end], namespace)
    exec(source[start:end], namespace)
    return namespace


def test_timeline_stream_reset_starts_new_segment_after_tools():
    helpers = _load_helpers()
    items: list[dict] = []
    apply = helpers["_apply_timeline_stream_update"]

    apply(items, domain="flood_damage", content="Looking up ", reset=True)
    apply(items, domain="flood_damage", content="Paris.", reset=False)
    items.append(
        {
            "kind": "tool",
            "tool_name": "stub_tool",
            "status": "success",
            "order": 1,
        }
    )
    apply(items, domain="flood_damage", content="Found ", reset=True)
    apply(items, domain="flood_damage", content="3 results.", reset=False)

    text_items = [i for i in items if i.get("kind") == "text"]
    assert len(text_items) == 2
    assert text_items[0]["message"] == "Looking up Paris."
    assert text_items[0]["open"] is False
    assert text_items[1]["message"] == "Found 3 results."
    assert items[1]["kind"] == "tool"


def test_agentic_node_stream_update_parsing():
    helpers = _load_helpers()
    assert helpers["_agentic_node_stream_update"](
        {
            "type": "graph_node",
            "phase": "streaming",
            "domain": "flood_damage",
            "content": "Hi",
            "reset": False,
        }
    ) == ("flood_damage", "Hi", False)
