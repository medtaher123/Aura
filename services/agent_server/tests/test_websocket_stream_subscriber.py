"""Tests for WebSocket stream subscriber tool step forwarding."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.websocket_stream_subscriber import WebSocketStreamSubscriber
from src.core.event_emitter import DataAgentStepEvent, EventEmitter
from src.tools.contracts import ToolArtifacts


@pytest.mark.asyncio
async def test_forward_tool_running_sends_tool_start() -> None:
    conn = MagicMock()
    conn.send_tool_start = AsyncMock()
    conn.send_tool_result = AsyncMock()
    subscriber = WebSocketStreamSubscriber(
        conn, MagicMock(), emitter=EventEmitter()
    )

    await subscriber._forward_tool_step(
        DataAgentStepEvent(
            phase="running",
            tool_name="request_location_user_input",
            tool_input={"location_query": "Pas-de-Calais, France"},
            step_id="s1",
            domain="flood_damage",
        )
    )

    conn.send_tool_start.assert_awaited_once_with(
        "request_location_user_input",
        {"location_query": "Pas-de-Calais, France"},
        step_id="s1",
        domain="flood_damage",
    )
    conn.send_tool_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_forward_tool_done_sends_tool_response_body() -> None:
    conn = MagicMock()
    conn.send_tool_start = AsyncMock()
    conn.send_tool_result = AsyncMock()
    subscriber = WebSocketStreamSubscriber(
        conn, MagicMock(), emitter=EventEmitter()
    )
    tool_response = {
        "message": "Several places match.",
        "tool_name": "request_location_user_input",
        "data": {"needs_input": {"location": {}}},
        "error": False,
        "artifacts": {"maps": [], "thumbnails": [], "urls": []},
    }

    await subscriber._forward_tool_step(
        DataAgentStepEvent(
            phase="done",
            tool_name="request_location_user_input",
            tool_input={"location_query": "Pas-de-Calais, France"},
            step_id="s1",
            domain="flood_damage",
            status="done",
            attempts=1,
            execution_time_seconds=0.909,
            observation="Several places match.",
            error=False,
            artifacts=ToolArtifacts(),
            result=tool_response,
        )
    )

    conn.send_tool_result.assert_awaited_once()
    kwargs = conn.send_tool_result.await_args.kwargs
    assert kwargs["tool_name"] == "request_location_user_input"
    assert kwargs["result"] == tool_response
    assert kwargs["step_id"] == "s1"
    assert kwargs["domain"] == "flood_damage"
    assert kwargs["execution_time_seconds"] == 0.909
    assert kwargs["status"] == "done"
    assert kwargs["attempts"] == 1
    assert kwargs["observation"] == "Several places match."
    assert kwargs["error"] is False
    assert kwargs["tool_input"] == {"location_query": "Pas-de-Calais, France"}
    conn.send_tool_start.assert_not_awaited()
