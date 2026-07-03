"""Unit tests for ToolPlanDomainNode base behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext


class _StubToolPlanDomainNode(ToolPlanDomainNode):
    @property
    def domain_name(self) -> str:
        return "stub_domain"

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


def test_tool_plan_domain_success_envelope(monkeypatch) -> None:
    class FakeAdapter:
        def select_tool_plan(self, *, domain: str, query: str):
            assert domain == "stub_domain"
            assert query == "fires near Paris"
            return SimpleNamespace(model_dump=lambda mode="python": {"domain": domain})

        def execute_tool_plan(self, **kwargs):
            step = SimpleNamespace(
                status="done",
                result={"message": "ok"},
                tool_name="stub_tool",
                input_arguments={"lat": 48.8566},
                model_dump=lambda mode="python": {"status": "done"},
            )
            return SimpleNamespace(
                steps=[step],
                summary=SimpleNamespace(
                    successful_steps=1,
                    model_dump=lambda mode="python": {"successful_steps": 1},
                ),
            )

    node = _StubToolPlanDomainNode(adapter=FakeAdapter())
    out = node(_state())
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "done"
    assert result["tool"] == "stub_tool"
    assert result["summary"]["successful_steps"] == 1


def test_tool_plan_domain_error_envelope() -> None:
    class FailingAdapter:
        def select_tool_plan(self, *, domain: str, query: str):
            raise RuntimeError("planner unavailable")

        def execute_tool_plan(self, **kwargs):
            raise AssertionError("should not execute")

    node = _StubToolPlanDomainNode(adapter=FailingAdapter())
    out = node(_state())
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "error"
    assert "planner unavailable" in result["message"]
    assert result["summary"]["successful_steps"] == 0
