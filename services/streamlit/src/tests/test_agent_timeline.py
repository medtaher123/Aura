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


def test_typewriter_advances_shown_toward_message():
    helpers = _load_helpers()
    items = [
        {
            "kind": "text",
            "domain": "flood_damage",
            "message": "Hello world",
            "shown": "Hel",
            "open": True,
        }
    ]
    assert helpers["_advance_timeline_typewriter"](items, chars=4) is True
    assert items[0]["shown"] == "Hello w"
    assert helpers["_advance_timeline_typewriter"](items, chars=100) is True
    assert items[0]["shown"] == "Hello world"


def test_typewriter_closes_only_after_catch_up():
    helpers = _load_helpers()
    items = [
        {
            "kind": "text",
            "domain": "flood_damage",
            "message": "Done",
            "shown": "Do",
            "open": True,
            "awaiting_close": True,
        }
    ]
    assert helpers["_timeline_typewriter_pending"](items) is True
    assert helpers["_advance_timeline_typewriter"](items, chars=1) is True
    assert items[0]["shown"] == "Don"
    assert items[0]["open"] is True
    assert helpers["_advance_timeline_typewriter"](items, chars=10) is True
    assert items[0]["shown"] == "Done"
    assert items[0]["open"] is False
    assert items[0]["awaiting_close"] is False
    assert helpers["_timeline_typewriter_pending"](items) is False


def test_snap_typewriter_reveals_full_text_immediately():
    helpers = _load_helpers()
    items = [
        {
            "kind": "text",
            "domain": "flood_damage",
            "message": "Full domain result",
            "shown": "Full",
            "open": True,
            "awaiting_close": True,
        }
    ]
    assert helpers["_snap_timeline_typewriter"](items) is True
    assert items[0]["shown"] == "Full domain result"
    assert items[0]["open"] is False
    assert items[0]["awaiting_close"] is False
    assert helpers["_timeline_typewriter_pending"](items) is False
    assert helpers["_snap_timeline_typewriter"](items) is False


def test_domain_markdown_renders_tables_without_stripping_blank_lines():
    """Domain results are Markdown; display must render tables (not strip newlines)."""
    from markdown_it import MarkdownIt

    sample = (
        "## Flood\n\n"
        "Intro paragraph.\n\n"
        "| Asset | Damage |\n"
        "|---|---|\n"
        "| Home | €1 |\n\n"
        "### Notes\n\n"
        "- one\n"
    )
    html_out = (
        MarkdownIt("commonmark", {"html": False}).enable("table").render(sample)
    )
    assert "<table>" in html_out
    assert "<th>" in html_out
    assert "<h2>" in html_out
    assert "Intro paragraph" in html_out


def test_domain_result_html_streaming_matches_completed_renderer():
    """Live typing must use the same Markdown box; cursor stays inline."""
    import html as html_mod
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    source = path.read_text(encoding="utf-8")
    start = source.index("def _domain_markdown_renderer")
    end = source.index("\ndef _render_tool_row", start)
    ns: dict = {"html": html_mod}
    exec(source[start:end], ns)

    sample = "## Flood\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    completed = ns["_domain_result_html"](sample, streaming=False)
    streaming = ns["_domain_result_html"](sample, streaming=True)
    assert completed.startswith("<div class='agent-domain-box'>")
    assert "<table>" in completed
    assert "<table>" in streaming
    assert "agent-domain-cursor" in streaming
    # Cursor sits inside the last cell, not after </table>.
    assert "</td><span class='agent-domain-cursor'>▌</span></td>" not in streaming
    assert "2<span class='agent-domain-cursor'>▌</span></td>" in streaming
    assert streaming.index("agent-domain-cursor") < streaming.rindex("</table>")

    paragraph = ns["_domain_result_html"]("Hello world", streaming=True)
    assert "Hello world<span class='agent-domain-cursor'>▌</span></p>" in paragraph
