"""Unit tests for AgenticDomainNode via AgenticTestNode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eo_llm.graph.nodes.domains.agentic_test_node import AgenticTestNode
from eo_llm.graph.nodes.domain_base import AgenticDomainNode
from eo_llm.graph.state import validate_state
from eo_llm.graph.transitions.domain_transitions import choose_after_domain


def test_agentic_test_node_extends_agentic_domain_node():
    node = AgenticTestNode()
    assert isinstance(node, AgenticDomainNode)
    assert node.domain_name == "agentic_test"


def test_agentic_test_node_tool_catalog():
    tool_names = [entry.name if hasattr(entry, "name") else entry for entry in AgenticTestNode.tools]
    assert "calculator" in tool_names
    assert "request_location_user_input" in tool_names
    assert "request_bounding_box_user_input" in tool_names


def test_agentic_test_node_registers_tools():
    tools = AgenticTestNode.resolved_tools()
    assert "calculator" in tools
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


@pytest.mark.asyncio
async def test_agentic_test_node_pauses_for_user_input():
    node = AgenticTestNode()
    run_result = MagicMock()
    run_result.paused = True
    run_result.needs_input = {"bounding_box": {"prompt": "Draw an area"}}
    run_result.error = False
    run_result.message = "Draw a box"
    run_result.tool_calls = []

    state = validate_state(
        {
            "query": "test",
            "user_query": "test",
            "selected_domains": ["agentic_test"],
        }
    )

    with patch.object(node._agent, "run", new=AsyncMock(return_value=run_result)):
        out = await node.execute(state)

    assert out["stopped_for_user_input"] is True
    assert out["domain_results"]["agentic_test"]["status"] == "paused"
    assert choose_after_domain(out) == "end"


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
