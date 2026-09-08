"""Tests for Bedrock converse_stream event accumulation."""

from __future__ import annotations

from eo_llm.adapters.bedrock.llm_providers.bedrockProvider import BedrockProvider


def test_accumulate_text_only_end_turn():
    deltas: list[str] = []
    events = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": "Hello "}}},
        {"contentBlockDelta": {"delta": {"text": "world"}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    result = BedrockProvider.accumulate_converse_stream_events(
        events, on_text_delta=deltas.append
    )
    assert deltas == ["Hello ", "world"]
    assert result.stop_reason == "end_turn"
    assert result.text == "Hello world"
    assert result.tool_calls == []


def test_accumulate_tool_use_with_json_deltas():
    events = [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockStart": {
                "start": {
                    "toolUse": {
                        "toolUseId": "tu-1",
                        "name": "stub_tool",
                    }
                }
            }
        },
        {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"loc'}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": 'ation":"Paris"}'}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]
    result = BedrockProvider.accumulate_converse_stream_events(events)
    assert result.stop_reason == "tool_use"
    assert result.text == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "tu-1"
    assert result.tool_calls[0].name == "stub_tool"
    assert result.tool_calls[0].arguments == {"location": "Paris"}
