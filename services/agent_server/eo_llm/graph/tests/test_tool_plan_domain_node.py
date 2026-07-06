"""Unit tests for ToolPlanDomainNode base behavior."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext
from eo_llm.graph.tool_plan import (
    ToolExecutionResult,
    ToolExecutionSummary,
    ToolPlan,
    ToolStepExecution,
    StopPolicy,
)


class _StubToolPlanDomainNode(ToolPlanDomainNode):
    domain_name = "stub_domain"
    tools = ["stub_tool"]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        return {"stub_tool": {"lat": float(ctx.lat), "lon": float(ctx.lon)}}


def _state(**overrides: Any) -> dict[str, Any]:
    base = {
        "query": "fires near Paris",
        "user_query": "fires near Paris",
        "selected_domains": ["stub_domain"],
        "resolved_location": {
            "display_name": "Paris, France",
            "lat": 48.8566,
            "lon": 2.3522,
        },
    }
    base.update(overrides)
    return base


def test_tool_plan_domain_not_selected_returns_empty() -> None:
    node = _StubToolPlanDomainNode()
    out = node(_state(selected_domains=["other"]))
    assert out == {}


def test_tool_plan_domain_skipped_without_coordinates() -> None:
    node = _StubToolPlanDomainNode()
    out = node(_state(resolved_location={"display_name": "Paris, France"}))
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "skipped"
    assert result["error"] is True
    assert "Missing resolved lat/lon" in result["message"]


def test_tool_plan_domain_success_envelope() -> None:
    class SuccessNode(_StubToolPlanDomainNode):
        def select_tool_plan(self, query: str) -> ToolPlan:
            assert query == "fires near Paris"
            return ToolPlan(
                domain="stub_domain",
                tool_steps=[],
                stop_policy=StopPolicy(),
            )

        def execute_tool_plan(self, **kwargs):
            step = ToolStepExecution(
                step_id="s1",
                tool_name="detect_fire_tool",
                status="done",
                attempts=1,
                latency_ms=1,
                input_arguments={"lat": 48.8566},
                result={"message": "ok"},
            )
            return ToolExecutionResult(
                domain="stub_domain",
                steps=[step],
                summary=ToolExecutionSummary(successful_steps=1),
            )

    node = SuccessNode()
    out = node(_state())
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "done"
    assert result["tool"] == "detect_fire_tool"
    assert result["summary"]["successful_steps"] == 1


def test_tool_plan_domain_tools_registry() -> None:
    from eo_llm.graph.builder import build_graph

    build_graph()
    assert ToolPlanDomainNode.tools_for("stac") == [
        "query_stac_catalog",
        "maxar_open_data_imagery_tool",
    ]
    assert ToolPlanDomainNode.tools_for("unknown") == []


def test_tool_plan_domain_error_envelope() -> None:
    class FailingNode(_StubToolPlanDomainNode):
        def select_tool_plan(self, query: str) -> ToolPlan:
            raise RuntimeError("planner unavailable")

        def execute_tool_plan(self, **kwargs):
            raise AssertionError("should not execute")

    node = FailingNode()
    out = node(_state())
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "error"
    assert "planner unavailable" in result["message"]
    assert result["summary"]["successful_steps"] == 0
