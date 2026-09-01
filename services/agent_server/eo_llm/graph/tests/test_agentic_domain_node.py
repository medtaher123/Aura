"""Unit tests for AgenticDomainNode via AgenticTestNode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eo_llm.graph.nodes.domains.agentic_test_node import AgenticTestNode
from eo_llm.graph.nodes.domain_base import AgenticDomainNode, ProviderTools
from eo_llm.graph.state import validate_state
from eo_llm.graph.tests.conftest import simulate_hitl_resume


def test_agentic_test_node_extends_agentic_domain_node():
    node = AgenticTestNode()
    assert isinstance(node, AgenticDomainNode)
    assert node.domain_name == "agentic_test"


def test_agentic_test_node_tool_catalog():
    assert AgenticTestNode.tools == [
        ProviderTools("native"),
        ProviderTools("nominatim"),
    ]


def test_agentic_test_node_registers_tools():
    tools = AgenticTestNode.resolved_tools()
    assert "web_search_tool" in tools
    assert AgenticTestNode.tools_for("agentic_test") == tools


@pytest.mark.asyncio
async def test_agentic_test_node_execute_success():
    node = AgenticTestNode()
    run_result = MagicMock()
    run_result.paused = False
    run_result.needs_input = None
    run_result.error = False
    run_result.message = "Calculator returned 42."
    run_result.tool_calls = []

    with patch.object(node._agent, "run", new=AsyncMock(return_value=run_result)):
        out = await node.execute(
            validate_state(
                {
                    "query": "what is 40 + 2",
                    "user_query": "what is 40 + 2",
                    "selected_domains": ["agentic_test"],
                }
            )
        )

    assert out["domain_results"]["agentic_test"]["status"] == "done"
    assert out["domain_results"]["agentic_test"]["message"] == "Calculator returned 42."
    assert out["domain_results"]["agentic_test"]["tool_messages"] == []


@pytest.mark.asyncio
async def test_agentic_test_node_success_emits_tool_messages():
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
    from src.tools.contracts import ToolResponse

    node = AgenticTestNode()
    record = AgentToolCallRecord(
        tool_use_id="calc-1",
        turn_index=0,
        tool_name="calculator",
        arguments={"expression": "40+2"},
        status="done",
        result=ToolResponse(message="42", tool_name="calculator", data={"value": 42}),
    )
    run_result = MagicMock()
    run_result.paused = False
    run_result.needs_input = None
    run_result.error = False
    run_result.message = "Calculator returned 42."
    run_result.tool_calls = [record]

    with patch.object(node._agent, "run", new=AsyncMock(return_value=run_result)):
        out = await node.execute(
            validate_state(
                {
                    "query": "what is 40 + 2",
                    "user_query": "what is 40 + 2",
                    "selected_domains": ["agentic_test"],
                }
            )
        )

    payload = out["domain_results"]["agentic_test"]
    assert payload["status"] == "done"
    assert len(payload["tool_messages"]) == 2
    assert payload["tool_messages"][0]["kind"] == "tool_call"
    assert payload["tool_messages"][1]["kind"] == "tool_result"
    assert payload["tool_messages"][0]["visible_to_ui"] is True
    assert payload["tool_messages"][0]["metadata"]["tool_name"] == "calculator"


@pytest.mark.asyncio
async def test_agentic_test_node_pauses_for_user_input(monkeypatch):
    node = AgenticTestNode()
    run_result = MagicMock()
    run_result.paused = True
    run_result.needs_input = {"bounding_box": {"prompt": "Draw an area"}}
    run_result.error = False
    run_result.message = "Draw a box"
    run_result.tool_calls = []

    async def fake_pause(self, s, client_payload, *, blob=None):
        return await simulate_hitl_resume(
            self,
            s,
            [
                {
                    "type": "bounding_box",
                    "area": {
                        "kind": "bounding_box",
                        "min_lat": 1.0,
                        "max_lat": 2.0,
                        "min_lon": 3.0,
                        "max_lon": 4.0,
                    },
                }
            ],
            blob=blob,
        )

    monkeypatch.setattr(AgenticDomainNode, "pause_for_hitl", fake_pause)

    success = MagicMock()
    success.paused = False
    success.needs_input = None
    success.error = False
    success.message = "Done after resume."
    success.tool_calls = run_result.tool_calls

    state = validate_state(
        {
            "query": "test",
            "user_query": "test",
            "selected_domains": ["agentic_test"],
        }
    )

    with patch.object(
        node._agent,
        "run",
        new=AsyncMock(side_effect=[run_result, success]),
    ):
        out = await node.execute(state)

    assert out["domain_results"]["agentic_test"]["status"] == "done"
    assert out["domain_results"]["agentic_test"]["message"] == "Done after resume."


@pytest.mark.asyncio
async def test_agentic_test_node_resumes_tool_records_from_hitl_blob(monkeypatch):
    from eo_llm.graph import hitl as hitl_store
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord

    node = AgenticTestNode()
    records = [
        AgentToolCallRecord(
            tool_use_id="t1",
            turn_index=0,
            tool_name="request_bounding_box_user_input",
            arguments={},
            status="done",
        )
    ]
    run_result = MagicMock()
    run_result.paused = False
    run_result.needs_input = None
    run_result.error = False
    run_result.message = "Done after resume."
    run_result.tool_calls = records

    state = validate_state(
        {
            "query": "test",
            "user_query": "test",
            "selected_domains": ["agentic_test"],
            "resolved_area": {
                "kind": "bounding_box",
                "min_lat": 1.0,
                "max_lat": 2.0,
                "min_lon": 3.0,
                "max_lon": 4.0,
            },
        }
    )

    captured: dict[str, object] = {}

    async def capture_run(**kwargs):
        captured["tool_call_records"] = kwargs.get("tool_call_records")
        return run_result

    thread_id = "agentic-resume-test"
    monkeypatch.setattr(hitl_store, "current_thread_id", lambda: thread_id)
    with hitl_store.hitl_resume_context(
        {
            "agentic_test": {
                "tool_call_records": [r.model_dump(mode="python") for r in records]
            }
        },
        thread_id=thread_id,
    ):
        with patch.object(node._agent, "run", new=AsyncMock(side_effect=capture_run)):
            out = await node.execute(state)

    assert captured["tool_call_records"] == records
    assert out["domain_results"]["agentic_test"]["status"] == "done"


@pytest.mark.asyncio
async def test_agentic_test_node_execute_failure():
    node = AgenticTestNode()

    with patch.object(
        node._agent,
        "run",
        new=AsyncMock(side_effect=RuntimeError("bedrock unavailable")),
    ):
        out = await node.execute(
            validate_state(
                {
                    "query": "test",
                    "user_query": "test",
                    "selected_domains": ["agentic_test"],
                }
            )
        )

    assert out["domain_results"]["agentic_test"]["status"] == "error"
    assert out["domain_results"]["agentic_test"]["error"] is True
