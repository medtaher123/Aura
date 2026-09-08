"""Tests for conversation history → Streamlit chat state mapping."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SRC = Path(__file__).resolve().parents[1]
_ROOT = _SRC.parent

# Ensure streamlit ``src`` package wins over other workspace ``src`` packages.
for path in (str(_ROOT), str(_SRC)):
    if path in sys.path:
        sys.path.remove(path)
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_SRC))

# Prefer absolute imports under streamlit/src as package root for ``models``.
_models = ModuleType("src.models")
_tools_path = _SRC / "models" / "tools.py"
_tools_spec = importlib.util.spec_from_file_location("src.models.tools", _tools_path)
assert _tools_spec and _tools_spec.loader
_tools = importlib.util.module_from_spec(_tools_spec)
sys.modules["src"] = ModuleType("src")
sys.modules["src.models"] = _models
sys.modules["src.models.tools"] = _tools
_tools_spec.loader.exec_module(_tools)
_models.tools = _tools  # type: ignore[attr-defined]

_hist_path = _SRC / "ui" / "conversation_history.py"
_hist_spec = importlib.util.spec_from_file_location(
    "conversation_history", _hist_path
)
assert _hist_spec and _hist_spec.loader
_hist = importlib.util.module_from_spec(_hist_spec)
_hist_spec.loader.exec_module(_hist)
conversation_messages_to_chat_state = _hist.conversation_messages_to_chat_state


def test_tool_call_result_pairs_attach_to_following_assistant():
    messages = [
        {"kind": "user_text", "role": "user", "content": "calc 1+1", "metadata": {}},
        {
            "kind": "tool_call",
            "role": "assistant",
            "content": "",
            "metadata": {
                "tool_use_id": "t1",
                "tool_name": "calculator",
                "arguments": {"expression": "1+1"},
            },
        },
        {
            "kind": "tool_result",
            "role": "user",
            "content": "",
            "metadata": {
                "tool_use_id": "t1",
                "status": "done",
                "latency_ms": 40,
                "result": {"message": "2", "tool_name": "calculator"},
            },
        },
        {
            "kind": "assistant_text",
            "role": "assistant",
            "content": "The answer is 2.",
            "metadata": {"error": False},
        },
    ]
    ui, agent = conversation_messages_to_chat_state(messages)
    assert len(ui) == 2
    assert ui[0]["role"] == "user"
    assert ui[1]["role"] == "assistant"
    assert ui[1]["content"] == "The answer is 2."
    tools = ui[1].get("tool_calls") or []
    assert len(tools) == 1
    assert tools[0]["tool_name"] == "calculator"
    assert tools[0]["status"] == "success"
    assert tools[0]["step_id"] == "t1"
    assert tools[0]["execution_time_seconds"] == 0.04
    assert tools[0]["arguments"] == {"expression": "1+1"}
    assert tools[0]["result"] == {"message": "2", "tool_name": "calculator"}
    assert agent[-1]["content"] == "The answer is 2."


def test_orphan_tool_rows_become_tool_only_assistant_bubble():
    messages = [
        {
            "kind": "tool_call",
            "role": "assistant",
            "content": "",
            "metadata": {"tool_use_id": "x", "tool_name": "web_search_tool"},
        },
        {
            "kind": "tool_result",
            "role": "user",
            "content": "",
            "metadata": {
                "tool_use_id": "x",
                "status": "error",
                "error_message": "timeout",
            },
        },
    ]
    ui, agent = conversation_messages_to_chat_state(messages)
    assert len(ui) == 1
    assert ui[0]["role"] == "assistant"
    assert ui[0]["content"] == ""
    tools = ui[0].get("tool_calls") or []
    assert tools[0]["status"] == "error"
    assert tools[0]["detail"] == "timeout"
    assert agent == []
