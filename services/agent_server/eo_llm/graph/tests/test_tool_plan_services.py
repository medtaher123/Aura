"""Unit tests for tool plan composition services."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from eo_llm.graph.tool_plan import (
    OnFailurePolicy,
    RetryPolicy,
    StopPolicy,
    ToolExecutor,
    ToolIntrospector,
    ToolPlan,
    ToolPlanner,
    ToolStepPlan,
)


def test_introspector_caches_metadata() -> None:
    cache: dict[str, dict[str, Any]] = {}
    introspector = ToolIntrospector(cache=cache)
    cache["demo_tool"] = {
        "all_params": ["lat", "lon"],
        "required_params": ["lat", "lon"],
        "docstring": "Demo tool",
    }

    first = introspector.get_metadata("demo_tool")
    second = introspector.get_metadata("demo_tool")

    assert first == second
    assert cache["demo_tool"]["docstring"] == "Demo tool"


def test_planner_select_tool_plan_validates_domain_and_tools() -> None:
    adapter = MagicMock()
    adapter.is_ready.return_value = True
    adapter.provider = MagicMock()
    adapter._tool_planner_model_id = "model-1"
    adapter.provider.last_failure_reason = ""
    adapter.provider.call_structured.return_value = ToolPlan(
        domain="fire_detection",
        tool_steps=[],
        stop_policy=StopPolicy(),
    )

    planner = ToolPlanner(
        adapter=adapter,
        domain="fire_detection",
        allowed_tools=["detect_fire_tool"],
    )
    plan = planner.select_tool_plan("fires near Paris")

    assert plan.domain == "fire_detection"


def test_planner_resolve_step_arguments_without_bedrock() -> None:
    introspector = ToolIntrospector(
        cache={
            "detect_fire_tool": {
                "all_params": ["lat", "lon"],
                "required_params": ["lat", "lon"],
                "docstring": "",
            }
        }
    )
    adapter = MagicMock()
    adapter.is_ready.return_value = False
    planner = ToolPlanner(
        adapter=adapter,
        domain="fire_detection",
        allowed_tools=["detect_fire_tool"],
        introspector=introspector,
    )
    step = ToolStepPlan(
        step_id="s1",
        tool_name="detect_fire_tool",
        priority=1,
        required_inputs=["lat"],
        retry_policy=RetryPolicy(),
        on_failure=OnFailurePolicy(),
    )
    plan = ToolPlan(domain="fire_detection", tool_steps=[step], stop_policy=StopPolicy())

    resolved = planner.resolve_step_arguments(
        plan=plan,
        step=step,
        candidate_args={"lat": 1.0, "lon": 2.0},
        execution_context={},
    )

    assert resolved["missing"] == []
    assert resolved["arguments"]["lat"] == 1.0


def test_executor_runs_tool_caller_and_records_success() -> None:
    planner = MagicMock()
    planner.resolve_step_arguments.return_value = {
        "arguments": {"lat": 48.0, "lon": 2.0},
        "missing": [],
    }
    calls: list[tuple[str, dict[str, Any]]] = []

    def tool_caller(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, args))
        return {"message": "ok", "data": {"found": True}}

    executor = ToolExecutor(tool_caller=tool_caller, planner=planner)
    step = ToolStepPlan(
        step_id="s1",
        tool_name="detect_fire_tool",
        priority=1,
        retry_policy=RetryPolicy(max_retries=0),
        on_failure=OnFailurePolicy(),
    )
    plan = ToolPlan(domain="fire_detection", tool_steps=[step], stop_policy=StopPolicy())
    result = executor.execute(
        plan=plan,
        runtime_args_by_tool={"detect_fire_tool": {"lat": 48.0, "lon": 2.0}},
    )

    assert calls == [("detect_fire_tool", {"lat": 48.0, "lon": 2.0})]
    assert result.summary.successful_steps == 1
    assert result.steps[0].status == "done"


def test_executor_skips_step_with_missing_required_inputs() -> None:
    planner = MagicMock()
    planner.resolve_step_arguments.return_value = {
        "arguments": {},
        "missing": ["lat"],
    }
    executor = ToolExecutor(tool_caller=MagicMock(), planner=planner)
    step = ToolStepPlan(
        step_id="s1",
        tool_name="detect_fire_tool",
        priority=1,
        retry_policy=RetryPolicy(),
        on_failure=OnFailurePolicy(),
    )
    plan = ToolPlan(domain="fire_detection", tool_steps=[step], stop_policy=StopPolicy())

    result = executor.execute(plan=plan, runtime_args_by_tool={})

    assert result.summary.skipped_steps == 1
    assert result.steps[0].status == "skipped"
