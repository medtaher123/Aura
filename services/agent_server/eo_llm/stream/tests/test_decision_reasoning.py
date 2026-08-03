"""Tests for decision reasoning stream helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from eo_llm.graph.tool_plan import StopPolicy, ToolPlan, ToolPlanner
from eo_llm.stream.decision_reasoning import (
    emit_decision_reasoning,
    format_decision_reasoning,
    register_formatter,
    thinking_payload_from_event,
)
from src.core.event_emitter import (
    EventEmitter,
    ThinkingStreamEvent,
    reset_stream_emitter,
    set_stream_emitter,
)


def test_format_route_domains_passes_through_agent_voice() -> None:
    line = format_decision_reasoning(
        ThinkingStreamEvent(
            source="route_domains",
            reasoning="User is asking for historical flood data in Pas-de-Calais.",
            context={"domains": ["flood_damage"]},
        )
    )
    assert line == "User is asking for historical flood data in Pas-de-Calais."


def test_format_tool_plan_converts_imperative_to_first_person() -> None:
    line = format_decision_reasoning(
        ThinkingStreamEvent(
            source="tool_plan",
            reasoning="Retrieve observed satellite flood data for November 2023.",
            context={"domain": "flood_damage", "tool_count": 1},
        )
    )
    assert (
        line
        == "I have to retrieve observed satellite flood data for November 2023."
    )


def test_format_tool_plan_keeps_existing_first_person() -> None:
    line = format_decision_reasoning(
        ThinkingStreamEvent(
            source="tool_plan",
            reasoning="I have to check active fire detections first.",
            context={"domain": "fire_detection", "tool_count": 1},
        )
    )
    assert line == "I have to check active fire detections first."


def test_emit_skips_empty_reasoning() -> None:
    events: list[Any] = []
    emitter = EventEmitter()
    emitter.add_listener(ThinkingStreamEvent, events.append)
    token = set_stream_emitter(emitter)
    try:
        emit_decision_reasoning("route_domains", "   ")
        emit_decision_reasoning("route_domains", "Ready.", domains=["stac"])
    finally:
        reset_stream_emitter(token)

    assert len(events) == 1
    assert isinstance(events[0], ThinkingStreamEvent)
    assert events[0].source == "route_domains"
    assert events[0].reasoning == "Ready."
    assert events[0].context["domains"] == ["stac"]


def test_thinking_payload_from_event() -> None:
    payload = thinking_payload_from_event(
        ThinkingStreamEvent(
            source="tool_plan",
            reasoning="Retrieve hazard map data first.",
            context={"domain": "flood_damage", "tool_count": 1},
        )
    )
    assert payload is not None
    assert payload["source"] == "tool_plan"
    assert payload["reasoning"] == "Retrieve hazard map data first."
    assert payload["stage"] == "tool_call"
    assert payload["content"] == "I have to retrieve hazard map data first."


def test_register_formatter_extends_display_without_changing_emitter() -> None:
    register_formatter(
        "custom_decision",
        lambda reasoning, context: f"Custom ({context.get('label')}): {reasoning}",
        stage="planning",
    )
    line = format_decision_reasoning(
        {
            "type": "thinking",
            "source": "custom_decision",
            "reasoning": "Because.",
            "label": "x",
        }
    )
    assert line == "Custom (x): Because."


@pytest.mark.asyncio
async def test_tool_planner_emits_reasoning() -> None:
    events: list[Any] = []
    emitter = EventEmitter()
    emitter.add_listener(ThinkingStreamEvent, events.append)
    token = set_stream_emitter(emitter)
    try:
        with patch(
            "eo_llm.graph.tool_plan.LLMModelRouter"
        ) as router_cls:
            router = router_cls.return_value
            router.call_structured = AsyncMock(
                return_value=ToolPlan(
                    domain="fire_detection",
                    tool_steps=[],
                    stop_policy=StopPolicy(),
                    reasoning="I have to check active fire detections first.",
                )
            )
            planner = ToolPlanner(
                domain="fire_detection",
                allowed_tools=["detect_fire_tool"],
            )
            await planner.select_tool_plan("fires near Paris")
    finally:
        reset_stream_emitter(token)

    assert len(events) == 1
    assert events[0].source == "tool_plan"
    assert events[0].context.get("domain") == "fire_detection"
    assert events[0].reasoning.startswith("I have to")
