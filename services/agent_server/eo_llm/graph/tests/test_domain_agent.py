"""Tests for agentic domain tool loop."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eo_llm.adapters.bedrock.llm_provider import ConverseResponse, ConverseToolCall
from eo_llm.graph.domain_agent import DomainToolAgent
from src.tools.contracts import ToolResponse
from src.tools.providers.base import ToolDescriptor


def _descriptor(name: str) -> ToolDescriptor:
    return ToolDescriptor(
        id=uuid4(),
        name=name,
        source="mcp",
        provider_id="metaplanet",
        description=f"Tool {name}",
        input_schema={
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": [],
        },
        enabled=True,
    )


@pytest.mark.asyncio
async def test_domain_tool_agent_final_answer_after_tool_use():
    agent = DomainToolAgent(max_rounds=3)
    descriptor = _descriptor("stub_tool")

    tool_response = ToolResponse(
        tool_name="stub_tool",
        message="Found 3 results",
        data={"count": 3},
        error=False,
    )

    converse_responses = [
        ConverseResponse(
            stop_reason="tool_use",
            tool_calls=[
                ConverseToolCall(
                    id="tu-1",
                    name="stub_tool",
                    arguments={"location": "Paris"},
                )
            ],
        ),
        ConverseResponse(
            stop_reason="end_turn",
            text="Paris has 3 matching assets.",
        ),
    ]

    mock_gateway = MagicMock()
    mock_gateway.list_tools.return_value = [descriptor]
    mock_gateway.invoke = AsyncMock(return_value=tool_response)

    with (
        patch("eo_llm.graph.domain_agent.LLMModelRouter") as router_cls,
        patch(
            "eo_llm.graph.domain_agent.get_tool_gateway",
            return_value=mock_gateway,
        ),
        patch(
            "eo_llm.graph.domain_agent.get_chat_history",
            return_value=[],
        ),
    ):
        mock_router = router_cls.return_value
        mock_router.call_converse_stream = AsyncMock(side_effect=converse_responses)
        result = await agent.run(
            domain="agentic_test",
            allowed_tools=["stub_tool"],
            system_prompt="You are a test agent.",
            runtime_args_by_tool={"stub_tool": {"lat": 48.8, "lon": 2.3}},
        )

    assert result.error is False
    assert result.paused is False
    assert result.message == "Paris has 3 matching assets."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments["location"] == "Paris"
    assert result.tool_calls[0].arguments["lat"] == 48.8
    assert result.tool_calls[0].tool_use_id == "tu-1"
    mock_gateway.invoke.assert_awaited_once_with(
        "stub_tool",
        {"lat": 48.8, "lon": 2.3, "location": "Paris"},
    )
    assert mock_router.call_converse_stream.await_count == 2
    second_call_kwargs = mock_router.call_converse_stream.await_args_list[1].kwargs
    assert "tool_call_records" not in second_call_kwargs
    chat_history = second_call_kwargs["chat_history"]
    expected_tool_messages = result.tool_calls[0].to_messages()
    assert len(chat_history) == len(expected_tool_messages)
    assert [m.kind for m in chat_history] == [m.kind for m in expected_tool_messages]
    assert chat_history[0].message_metadata["tool_use_id"] == "tu-1"


@pytest.mark.asyncio
async def test_domain_tool_agent_emits_node_token_reset_and_deltas():
    agent = DomainToolAgent(max_rounds=2)
    descriptor = _descriptor("stub_tool")
    emitted: list[Any] = []

    async def _stream(**kwargs):
        on_delta = kwargs.get("on_text_delta")
        if on_delta:
            on_delta("Partial ")
            on_delta("answer.")
        return ConverseResponse(stop_reason="end_turn", text="Partial answer.")

    mock_gateway = MagicMock()
    mock_gateway.list_tools.return_value = [descriptor]

    with (
        patch("eo_llm.graph.domain_agent.LLMModelRouter") as router_cls,
        patch(
            "eo_llm.graph.domain_agent.get_tool_gateway",
            return_value=mock_gateway,
        ),
        patch("eo_llm.graph.domain_agent.get_chat_history", return_value=[]),
        patch("eo_llm.graph.domain_agent.emit_event", side_effect=emitted.append),
    ):
        mock_router = router_cls.return_value
        mock_router.call_converse_stream = AsyncMock(side_effect=_stream)
        result = await agent.run(
            domain="flood_damage",
            allowed_tools=["stub_tool"],
            system_prompt="test",
            node_name="flood_damage",
        )

    assert result.message == "Partial answer."
    from src.core.event_emitter import GraphNodeTokenEvent

    token_events = [e for e in emitted if isinstance(e, GraphNodeTokenEvent)]
    assert token_events[0].reset is True
    assert token_events[0].domain == "flood_damage"
    assert [(e.content, e.reset) for e in token_events[1:]] == [
        ("Partial ", False),
        ("answer.", False),
    ]


@pytest.mark.asyncio
async def test_domain_tool_agent_pauses_on_user_input_tool():
    agent = DomainToolAgent(max_rounds=2)
    descriptor = _descriptor("request_bounding_box_user_input")
    pause_response = ToolResponse(
        tool_name="request_bounding_box_user_input",
        message="Draw a box",
        data={
            "stopped_for_user_input": True,
            "needs_input": {
                "bounding_box": {"prompt": "Draw the area"},
            },
        },
        error=False,
    )

    mock_gateway = MagicMock()
    mock_gateway.list_tools.return_value = [descriptor]
    mock_gateway.invoke = AsyncMock(return_value=pause_response)

    with (
        patch("eo_llm.graph.domain_agent.LLMModelRouter") as router_cls,
        patch(
            "eo_llm.graph.domain_agent.get_tool_gateway",
            return_value=mock_gateway,
        ),
        patch("eo_llm.graph.domain_agent.get_chat_history", return_value=[]),
    ):
        mock_router = router_cls.return_value
        mock_router.call_converse_stream = AsyncMock(
            return_value=ConverseResponse(
                stop_reason="tool_use",
                tool_calls=[
                    ConverseToolCall(
                        id="tu-1",
                        name="request_bounding_box_user_input",
                        arguments={"prompt": "Draw the area"},
                    )
                ],
            )
        )
        result = await agent.run(
            domain="flood_damage",
            allowed_tools=["request_bounding_box_user_input"],
            system_prompt="test",
        )

    assert result.paused is True
    assert result.needs_input == {"bounding_box": {"prompt": "Draw the area"}}


@pytest.mark.asyncio
async def test_domain_tool_agent_runs_same_turn_tools_in_parallel():
    agent = DomainToolAgent(max_rounds=2)
    descriptors = [_descriptor("tool_a"), _descriptor("tool_b")]
    started: list[str] = []
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def _invoke(tool_name: str, _args: dict[str, Any]) -> ToolResponse:
        started.append(tool_name)
        if len(started) >= 2:
            both_started.set()
        await release.wait()
        return ToolResponse(
            tool_name=tool_name,
            message=f"{tool_name} ok",
            data={},
            error=False,
        )

    mock_gateway = MagicMock()
    mock_gateway.list_tools.return_value = descriptors
    mock_gateway.invoke = AsyncMock(side_effect=_invoke)

    with (
        patch("eo_llm.graph.domain_agent.LLMModelRouter") as router_cls,
        patch(
            "eo_llm.graph.domain_agent.get_tool_gateway",
            return_value=mock_gateway,
        ),
        patch("eo_llm.graph.domain_agent.get_chat_history", return_value=[]),
    ):
        mock_router = router_cls.return_value
        mock_router.call_converse_stream = AsyncMock(
            side_effect=[
                ConverseResponse(
                    stop_reason="tool_use",
                    tool_calls=[
                        ConverseToolCall(id="a", name="tool_a", arguments={}),
                        ConverseToolCall(id="b", name="tool_b", arguments={}),
                    ],
                ),
                ConverseResponse(stop_reason="end_turn", text="done"),
            ]
        )
        run_task = asyncio.create_task(
            agent.run(
                domain="agentic_test",
                allowed_tools=["tool_a", "tool_b"],
                system_prompt="test",
            )
        )
        await asyncio.wait_for(both_started.wait(), timeout=1.0)
        release.set()
        result = await asyncio.wait_for(run_task, timeout=1.0)

    assert result.message == "done"
    assert [c.tool_name for c in result.tool_calls] == ["tool_a", "tool_b"]
    assert mock_gateway.invoke.await_count == 2
