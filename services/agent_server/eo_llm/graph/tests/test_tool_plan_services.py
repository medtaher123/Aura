"""Unit tests for tool plan composition services."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

from eo_llm.adapters.mcp_client import reset_stream_callback, set_stream_callback
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


def test_executor_runs_same_priority_tools_in_parallel() -> None:
    planner = MagicMock()
    planner.resolve_step_arguments.return_value = {
        "arguments": {"lat": 48.0, "lon": 2.0},
        "missing": [],
    }
    active = 0
    peak = 0
    lock = threading.Lock()

    def tool_caller(name: str, args: dict[str, Any]) -> dict[str, Any]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"message": name, "error": False}

    executor = ToolExecutor(tool_caller=tool_caller, planner=planner)
    steps = [
        ToolStepPlan(
            step_id="s1",
            tool_name="detect_fire_tool",
            priority=1,
            retry_policy=RetryPolicy(max_retries=0),
            on_failure=OnFailurePolicy(),
        ),
        ToolStepPlan(
            step_id="s2",
            tool_name="clms_burnt_area_impact_tool",
            priority=1,
            retry_policy=RetryPolicy(max_retries=0),
            on_failure=OnFailurePolicy(),
        ),
    ]
    plan = ToolPlan(domain="fire_detection", tool_steps=steps, stop_policy=StopPolicy())
    result = executor.execute(plan=plan, runtime_args_by_tool={})

    assert result.summary.successful_steps == 2
    assert peak >= 2


def test_executor_batches_by_priority() -> None:
    batches = ToolExecutor._batch_steps(
        [
            ToolStepPlan(
                step_id="s1",
                tool_name="detect_fire_tool",
                priority=1,
                retry_policy=RetryPolicy(),
                on_failure=OnFailurePolicy(),
            ),
            ToolStepPlan(
                step_id="s2",
                tool_name="clms_burnt_area_impact_tool",
                priority=1,
                retry_policy=RetryPolicy(),
                on_failure=OnFailurePolicy(),
            ),
            ToolStepPlan(
                step_id="s3",
                tool_name="query_disaster_events_tool",
                priority=2,
                retry_policy=RetryPolicy(),
                on_failure=OnFailurePolicy(),
            ),
        ]
    )
    assert len(batches) == 2
    assert len(batches[0]) == 2
    assert len(batches[1]) == 1


def test_executor_emits_tool_start_and_done_events() -> None:
    planner = MagicMock()
    planner.resolve_step_arguments.return_value = {
        "arguments": {"lat": 48.0, "lon": 2.0},
        "missing": [],
    }
    events: list[dict[str, Any]] = []
    token = set_stream_callback(events.append)

    def tool_caller(name: str, args: dict[str, Any]) -> dict[str, Any]:
        time.sleep(0.02)
        return {"message": "ok", "error": False}

    try:
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
            execution_context={"domain": "fire_detection"},
        )
    finally:
        reset_stream_callback(token)

    assert result.summary.successful_steps == 1
    assert len(events) == 2
    assert events[0]["phase"] == "running"
    assert events[0]["tool_name"] == "detect_fire_tool"
    assert events[0]["step_id"] == "s1"
    assert events[0]["domain"] == "fire_detection"
    assert events[1]["phase"] == "done"
    assert events[1]["status"] == "done"
    assert events[1]["execution_time_seconds"] >= 0.02
    assert events[1]["attempts"] == 1
    assert events[1]["error"] is False


def test_executor_emits_done_event_on_tool_error() -> None:
    planner = MagicMock()
    planner.resolve_step_arguments.return_value = {
        "arguments": {"lat": 48.0, "lon": 2.0},
        "missing": [],
    }
    events: list[dict[str, Any]] = []
    token = set_stream_callback(events.append)

    def tool_caller(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"message": "failed", "error": True}

    try:
        executor = ToolExecutor(tool_caller=tool_caller, planner=planner)
        step = ToolStepPlan(
            step_id="s1",
            tool_name="detect_fire_tool",
            priority=1,
            retry_policy=RetryPolicy(max_retries=0),
            on_failure=OnFailurePolicy(),
        )
        plan = ToolPlan(domain="fire_detection", tool_steps=[step], stop_policy=StopPolicy())
        executor.execute(plan=plan, runtime_args_by_tool={})
    finally:
        reset_stream_callback(token)

    done_events = [event for event in events if event.get("phase") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["status"] == "error"
    assert done_events[0]["error"] is True
