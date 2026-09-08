"""Tests for agentic node start caption + result entry + streaming draft mapping."""

from __future__ import annotations

from pathlib import Path


def _load_helpers():
    path = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    source = path.read_text(encoding="utf-8")
    start = source.index("def _is_node_progress_event")
    end = source.index("\ndef _render_node_start_lines", start)
    namespace: dict = {"html": __import__("html")}
    exec(source[start:end], namespace)
    return namespace


def test_agentic_node_start_line():
    helpers = _load_helpers()
    line = helpers["_agentic_node_start_line"](
        {
            "type": "graph_node",
            "phase": "running",
            "node_name": "flood_damage",
            "domain": "flood_damage",
            "message": "Analyzing floods...",
        }
    )
    assert line == "flood_damage · Analyzing floods..."


def test_agentic_node_result_entry_from_lifecycle_payload():
    helpers = _load_helpers()
    entry = helpers["_agentic_node_result_entry"](
        {
            "type": "graph_node",
            "phase": "done",
            "node_name": "flood_damage",
            "domain": "flood_damage",
            "message": "Flood analysis complete for Pas-de-Calais.",
            "result": {
                "domain": "flood_damage",
                "status": "done",
                "message": "Flood analysis complete for Pas-de-Calais.",
                "error": False,
                "tool_call_count": 2,
            },
        }
    )
    assert entry == {
        "domain": "flood_damage",
        "message": "Flood analysis complete for Pas-de-Calais.",
    }


def test_non_domain_node_start_ignored():
    helpers = _load_helpers()
    assert (
        helpers["_agentic_node_start_line"](
            {
                "type": "graph_node",
                "phase": "running",
                "node_name": "orchestrator",
                "message": "Planning your request...",
            }
        )
        is None
    )


def test_status_chrome_on_done_ignored():
    helpers = _load_helpers()
    assert (
        helpers["_agentic_node_result_entry"](
            {
                "type": "graph_node",
                "phase": "done",
                "domain": "flood_damage",
                "result": {
                    "domain": "flood_damage",
                    "message": "Analyzing floods...",
                    "tool_call_count": 0,
                },
            }
        )
        is None
    )


def test_streaming_reset_and_append_grows_draft():
    helpers = _load_helpers()
    results: list[dict[str, str]] = []
    upsert = helpers["_upsert_streaming_node_result"]

    reset = helpers["_agentic_node_stream_update"](
        {
            "type": "graph_node",
            "phase": "streaming",
            "domain": "flood_damage",
            "content": "",
            "reset": True,
        }
    )
    assert reset == ("flood_damage", "", True)
    upsert(results, domain=reset[0], content=reset[1], reset=reset[2])

    for chunk in ("Flood ", "analysis ", "complete."):
        update = helpers["_agentic_node_stream_update"](
            {
                "type": "graph_node",
                "phase": "streaming",
                "domain": "flood_damage",
                "content": chunk,
                "reset": False,
            }
        )
        assert update is not None
        upsert(results, domain=update[0], content=update[1], reset=update[2])

    assert results == [
        {"domain": "flood_damage", "message": "Flood analysis complete."}
    ]


def test_streaming_reset_clears_prior_draft():
    helpers = _load_helpers()
    results = [{"domain": "flood_damage", "message": "stale draft"}]
    upsert = helpers["_upsert_streaming_node_result"]
    upsert(results, domain="flood_damage", content="", reset=True)
    upsert(results, domain="flood_damage", content="new text", reset=False)
    assert results == [{"domain": "flood_damage", "message": "new text"}]
