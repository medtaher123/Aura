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


def test_agentic_node_lifecycle_result_is_ui_friendly():
    node = AgenticTestNode()
    payload = node.node_lifecycle_result(
        {
            "domain_results": {
                "agentic_test": {
                    "status": "done",
                    "message": "Flood analysis complete.",
                    "error": False,
                    "tool": "terrazard_flood_briefing",
                    "result": {"message": "ok"},
                    "tool_calls": [{"tool_name": "a"}, {"tool_name": "b"}],
                    "tool_messages": [{"kind": "tool_call"}, {"kind": "tool_result"}],
                    "resolved_location": {"name": "Paris"},
                }
            }
        }
    )
    assert payload is not None
    assert payload["domain"] == "agentic_test"
    assert payload["message"] == "Flood analysis complete."
    assert payload["status"] == "done"
    assert payload["error"] is False
    assert payload["tool"] == "terrazard_flood_briefing"
    assert payload["result"] == {"message": "ok"}
    assert payload["tool_call_count"] == 2
    assert payload["resolved_location"] == {"name": "Paris"}
    assert "tool_messages" not in payload
    assert "tool_calls" not in payload


def test_domain_nodes_extend_agentic_domain_node():
    from eo_llm.graph.nodes.domains.disaster_detection_node import (
        DisasterDetectionNode,
    )
    from eo_llm.graph.nodes.domains.fire_detection_node import FireDetectionNode
    from eo_llm.graph.nodes.domains.flood_damage_node import FloodDamageNode
    from eo_llm.graph.nodes.domains.infrastructure_node import InfrastructureNode
    from eo_llm.graph.nodes.domains.stac_node import StacNode

    for node_cls in (
        DisasterDetectionNode,
        FireDetectionNode,
        FloodDamageNode,
        InfrastructureNode,
        StacNode,
    ):
        assert isinstance(node_cls(), AgenticDomainNode)


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
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
    from src.tools.contracts import ToolResponse

    node = AgenticTestNode()
    paused_record = AgentToolCallRecord(
        tool_use_id="bbox-1",
        turn_index=0,
        tool_name="request_bounding_box_user_input",
        arguments={},
        status="done",
        result=ToolResponse(
            tool_name="request_bounding_box_user_input",
            message="Draw a box",
            data={
                "needs_input": {"bounding_box": {"prompt": "Draw an area"}},
                "stopped_for_user_input": True,
                "input_kind": "bounding_box",
            },
        ),
    )
    run_result = MagicMock()
    run_result.paused = True
    run_result.needs_input = {"bounding_box": {"prompt": "Draw an area"}}
    run_result.error = False
    run_result.message = "Draw a box"
    run_result.tool_calls = [paused_record]

    captured: dict[str, object] = {}

    async def fake_pause(self, s, client_payload, *, blob=None):
        captured["blob"] = blob
        captured["payload"] = client_payload
        raise RuntimeError("simulated interrupt")

    monkeypatch.setattr(AgenticDomainNode, "pause_for_hitl", fake_pause)

    state = validate_state(
        {
            "query": "test",
            "user_query": "test",
            "selected_domains": ["agentic_test"],
        }
    )

    with patch.object(node._agent, "run", new=AsyncMock(return_value=run_result)):
        with pytest.raises(RuntimeError, match="simulated interrupt"):
            await node.execute(state)

    assert captured["blob"] is not None
    assert "tool_call_records" in captured["blob"]  # type: ignore[operator]
    assert captured["payload"]["data"]["needs_input"]["bounding_box"]["prompt"] == (
        "Draw an area"
    )


@pytest.mark.asyncio
async def test_agentic_test_node_patches_user_input_on_resume(monkeypatch):
    from eo_llm.graph import hitl as hitl_store
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
    from src.tools.contracts import ToolResponse

    node = AgenticTestNode()
    paused_record = AgentToolCallRecord(
        tool_use_id="bbox-1",
        turn_index=0,
        tool_name="request_bounding_box_user_input",
        arguments={},
        status="done",
        result=ToolResponse(
            tool_name="request_bounding_box_user_input",
            message="Draw a box",
            data={
                "needs_input": {"bounding_box": {"prompt": "Draw an area"}},
                "stopped_for_user_input": True,
                "input_kind": "bounding_box",
            },
        ),
    )
    attachments = [
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
    ]
    blob = {
        "tool_call_records": [paused_record.model_dump(mode="python")],
    }
    state = await simulate_hitl_resume(
        node,
        validate_state(
            {
                "query": "test",
                "user_query": "test",
                "selected_domains": ["agentic_test"],
            }
        ),
        attachments,
        blob=blob,
    )

    success = MagicMock()
    success.paused = False
    success.needs_input = None
    success.error = False
    success.message = "Done after resume."
    success.tool_calls = []

    captured: dict[str, object] = {}

    async def fake_run(**kwargs):
        captured["tool_call_records"] = kwargs.get("tool_call_records")
        success.tool_calls = list(kwargs.get("tool_call_records") or [])
        return success

    thread_id = "agentic-patch-resume-test"
    monkeypatch.setattr(hitl_store, "current_thread_id", lambda: thread_id)
    with hitl_store.hitl_resume_context(
        {"agentic_test": blob},
        attachments=attachments,
        thread_id=thread_id,
    ):
        with patch.object(node._agent, "run", new=AsyncMock(side_effect=fake_run)):
            out = await node.execute(state)

    assert out["domain_results"]["agentic_test"]["status"] == "done"
    assert out["domain_results"]["agentic_test"]["message"] == "Done after resume."
    records = captured["tool_call_records"]
    assert isinstance(records, list) and len(records) == 1
    patched = records[0]
    assert patched.tool_name == "request_bounding_box_user_input"
    assert patched.result is not None
    assert patched.result.data.get("stopped_for_user_input") is False
    assert patched.result.data.get("user_answer", {}).get("type") == "bounding_box"
    assert "Selected area" in patched.result.message


@pytest.mark.asyncio
async def test_agentic_test_node_restarts_from_top_after_hitl_resume(monkeypatch):
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
    from src.tools.contracts import ToolResponse

    node = AgenticTestNode()
    paused_record = AgentToolCallRecord(
        tool_use_id="bbox-1",
        turn_index=0,
        tool_name="request_bounding_box_user_input",
        arguments={},
        status="done",
        result=ToolResponse(
            tool_name="request_bounding_box_user_input",
            message="Draw a box",
            data={
                "needs_input": {"bounding_box": {"prompt": "Draw an area"}},
                "stopped_for_user_input": True,
                "input_kind": "bounding_box",
            },
        ),
    )
    paused = MagicMock()
    paused.paused = True
    paused.needs_input = {"bounding_box": {"prompt": "Draw an area"}}
    paused.error = False
    paused.message = "Draw a box"
    paused.tool_calls = [paused_record]

    success = MagicMock()
    success.paused = False
    success.needs_input = None
    success.error = False
    success.message = "Done after resume."
    success.tool_calls = []

    async def fake_pause(self, s, client_payload, *, blob=None):
        payload_blob = blob if blob is not None else self.serialize_hitl_blob(s)
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
            blob=payload_blob,
        )

    monkeypatch.setattr(AgenticDomainNode, "pause_for_hitl", fake_pause)

    run_mock = AsyncMock(side_effect=[paused, success])
    state = validate_state(
        {
            "query": "test",
            "user_query": "test",
            "selected_domains": ["agentic_test"],
        }
    )

    with patch.object(node._agent, "run", new=run_mock):
        out = await node.execute(state)

    assert run_mock.await_count == 2
    assert out["domain_results"]["agentic_test"]["status"] == "done"
    assert out["domain_results"]["agentic_test"]["message"] == "Done after resume."


def test_with_user_input_answers_matches_input_kind():
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
    from src.tools.contracts import ToolResponse

    record = AgentToolCallRecord(
        tool_use_id="loc-1",
        tool_name="request_location_user_input",
        arguments={"location_query": "Paris"},
        result=ToolResponse(
            tool_name="request_location_user_input",
            message="Pick a place",
            data={
                "needs_input": {"location": {"candidates": []}},
                "stopped_for_user_input": True,
                "input_kind": "location",
            },
        ),
    )
    patched = AgenticDomainNode._with_user_input_answers(
        [record],
        [
            {
                "type": "location",
                "name": "Paris, France",
                "coordinates": [48.85, 2.35],
            }
        ],
    )
    assert len(patched) == 1
    assert patched[0].result is not None
    assert patched[0].result.data["stopped_for_user_input"] is False
    assert patched[0].result.data["user_answer"]["name"] == "Paris, France"
    assert "Confirmed location" in patched[0].result.message


def test_with_user_input_answers_skips_without_input_kind():
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
    from src.tools.contracts import ToolResponse

    record = AgentToolCallRecord(
        tool_use_id="loc-1",
        tool_name="request_location_user_input",
        result=ToolResponse(
            tool_name="request_location_user_input",
            message="Pick a place",
            data={"stopped_for_user_input": True},
        ),
    )
    patched = AgenticDomainNode._with_user_input_answers(
        [record],
        [{"type": "location", "name": "Paris", "coordinates": [48.85, 2.35]}],
    )
    assert patched[0].result is not None
    assert patched[0].result.data.get("stopped_for_user_input") is True


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
