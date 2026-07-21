"""Domain tool planning and execution models and services."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import pkgutil
import time
from datetime import datetime, timezone
from itertools import groupby
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.adapters.bedrock.llm_model_router import LLMModelRouter
from eo_llm.adapters.mcp_client import MCPClient
from src.core.event_emitter import DataAgentStepEvent, emit_event
from eo_llm.stream.decision_reasoning import emit_decision_reasoning
from eo_llm.graph.backoff import backoff_strategy_for
from eo_llm.prompts import get_arg_resolver_prompt, get_tool_planner_prompt
from src.core.singleton_meta import SingletonMeta
from src.tools.contracts import ToolArtifacts, ToolResponse


DomainName = Literal[
    "flood_damage",
    "fire_detection",
    "disaster_detection",
    "infrastructure",
    "stac",
]
ToolName = Literal[
    "get_terrazard_available_dates_tool",
    "get_terrazard_hazard_map_tool",
    "get_terrazard_flood_briefing_tool",
    "get_terrazard_flood_damage_tool",
    "geoserver_risk_mask_tool",
    "flood_damage_city_tool",
    "flood_depth_damage_tool",
    "streamflow_forecast_tool",
    "estimate_surface_water_ingress_tool",
    "bdtopo_visualize_tool",
    "detect_fire_tool",
    "clms_burnt_area_impact_tool",
    "query_disaster_events_tool",
    "clms_land_cover_exposure_tool",
    "cems_rapid_mapping_events_tool",
    "infrastructure_query_tool",
    "get_route_info",
    "query_stac_catalog",
    "maxar_open_data_imagery_tool",
    "web_search_tool",
    "bdtopo_query_tool",
    "bdtopo_intersection_tool",
    "bdtopo_thematic_explain_tool",
]
BackoffMode = Literal["none", "fixed", "exponential_jitter"]
FailureAction = Literal["continue", "fallback_to_step", "abort_domain"]
StopMode = Literal["run_all", "stop_on_first_success", "stop_on_confidence"]
ErrorType = Literal[
    "timeout",
    "network_error",
    "http_429",
    "http_5xx",
    "validation_error",
    "empty_result",
    "unknown",
]
RetryTrigger = Literal["timeout", "network_error", "http_429", "http_5xx", "empty_result"]


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=1)
    backoff: BackoffMode = "fixed"
    initial_delay_ms: int = Field(default=300)
    retry_on: list[RetryTrigger] = Field(
        default_factory=lambda: ["timeout", "network_error", "http_429", "http_5xx"]
    )


class OnFailurePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: FailureAction = "continue"
    fallback_to_step_id: str | None = None


class StopPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: StopMode = "run_all"
    confidence_threshold: float = Field(default=0.8)
    min_successful_steps: int = Field(default=1)


class ToolStepPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    tool_name: ToolName
    priority: int = Field()
    required_inputs: list[str] = Field(default_factory=list)
    parallel_group: str | None = None
    args_template: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": False}
    )
    retry_policy: RetryPolicy
    timeout_seconds: int = Field(default=30)
    on_failure: OnFailurePolicy
    success_weight: float = Field(default=0.2)


class ToolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    tool_steps: list[ToolStepPlan] = Field(default_factory=list)
    stop_policy: StopPolicy
    reasoning: str = ""


class ToolStepExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    tool_name: ToolName
    status: Literal["done", "error", "skipped"]
    attempts: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    error_type: ErrorType | None = None
    error_message: str | None = None
    input_arguments: dict[str, Any] | None = None
    result: ToolResponse | None = None


class ToolExecutionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successful_steps: int = Field(default=0, ge=0)
    failed_steps: int = Field(default=0, ge=0)
    skipped_steps: int = Field(default=0, ge=0)
    domain_confidence: float = Field(default=0.0)
    fallback_triggered: bool = False


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    steps: list[ToolStepExecution] = Field(default_factory=list)
    summary: ToolExecutionSummary


class ArgumentKV(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value_json: str


class StepArgumentResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: list[ArgumentKV] = Field(default_factory=list)
    covered_required_inputs: list[str] = Field(default_factory=list)
    unresolved_required_inputs: list[str] = Field(default_factory=list)
    notes: str = ""

#TODO: is this class used?? (mtbh)
class ToolIntrospector(metaclass=SingletonMeta):
    """Fetches and caches MCP tool parameter metadata."""

    def __init__(self, cache: dict[str, dict[str, Any]] | None = None) -> None:
        self._cache = cache if cache is not None else {}

    async def get_metadata(self, tool_name: str) -> dict[str, Any]:
        cached = self._cache.get(tool_name)
        if cached is not None:
            return cached

        meta: dict[str, Any] = {
            "all_params": [],
            "required_params": [],
            "docstring": "",
        }

        try:
            fetched = await MCPClient().get_tool_metadata(tool_name)
            if fetched and fetched.get("all_params"):
                meta = {
                    "all_params": list(fetched.get("all_params") or []),
                    "required_params": list(fetched.get("required_params") or []),
                    "docstring": str(fetched.get("docstring") or ""),
                }
                self._cache[tool_name] = meta
                return meta
        except Exception:
            pass

        try:
            tools_pkg = importlib.import_module("eo_llm.mcp_server.tools")
            pkg_path = getattr(tools_pkg, "__path__", None)
            if pkg_path is None:
                self._cache[tool_name] = meta
                return meta
            for mod in pkgutil.iter_modules(pkg_path):
                module_name = f"{tools_pkg.__name__}.{mod.name}"
                try:
                    module = importlib.import_module(module_name)
                except Exception:
                    continue
                fn = getattr(module, tool_name, None)
                if not callable(fn):
                    continue
                sig = inspect.signature(fn)
                all_params: list[str] = []
                required_params: list[str] = []
                for p in sig.parameters.values():
                    if p.kind in (
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    ):
                        all_params.append(p.name)
                        if p.default is inspect._empty:
                            required_params.append(p.name)
                meta = {
                    "all_params": all_params,
                    "required_params": required_params,
                    "docstring": inspect.getdoc(fn) or "",
                }
                break
        except Exception:
            meta = {"all_params": [], "required_params": [], "docstring": ""}

        self._cache[tool_name] = meta
        return meta


class ToolPlanner:
    """Generates tool execution plans and resolves step arguments via Bedrock."""

    def __init__(
        self,
        domain: str,
        allowed_tools: list[str],
    ) -> None:
        self._domain = domain
        self._allowed_tools = allowed_tools

    async def select_tool_plan(self, query: str) -> ToolPlan:
        
        system_prompt, user_prompt = get_tool_planner_prompt(
            domain=self._domain,
            query=query,
            allowed_tools=self._allowed_tools,
        )
        candidate = await LLMModelRouter().call_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ToolPlan,
            schema_name="domain_tool_plan",
            schema_description="Execution plan for a single EO_LLM domain agent",
            max_tokens=1200,
        )

        emit_decision_reasoning(
            "tool_plan",
            candidate.reasoning,
            domain=self._domain,
            tool_count=len(candidate.tool_steps),
        )
        return candidate

    async def resolve_step_arguments(
        *,
        plan: ToolPlan,
        step: ToolStepPlan,
        candidate_args: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        tool_meta = await ToolIntrospector().get_metadata(step.tool_name)
        tool_param_names = list(tool_meta.get("all_params") or [])
        required_params = list(tool_meta.get("required_params") or [])
        docstring = str(tool_meta.get("docstring") or "")

        if ( tool_param_names):
            today_utc = datetime.now(timezone.utc).date().isoformat()
            system_prompt, user_prompt = get_arg_resolver_prompt(
                today_utc=today_utc,
                domain=plan.domain,
                tool_name=step.tool_name,
                required_inputs=list(step.required_inputs),
                tool_param_names=tool_param_names,
                required_params=required_params,
                docstring=docstring,
                candidate_args=candidate_args,
                execution_context=execution_context,
            )
            parsed = await LLMModelRouter().call_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=StepArgumentResolution,
                schema_name="step_argument_resolution",
                schema_description="Resolved concrete arguments for one tool step",
                max_tokens=900,
            )
            if parsed is not None:
                resolved_args: dict[str, Any] = {}
                for item in parsed.arguments:
                    if tool_param_names and item.name not in tool_param_names:
                        continue
                    try:
                        resolved_args[item.name] = json.loads(item.value_json)
                    except Exception:
                        resolved_args[item.name] = item.value_json
                merged = {
                    k: v
                    for k, v in candidate_args.items()
                    if not tool_param_names or k in tool_param_names
                }
                merged.update(resolved_args)
                missing = [x for x in parsed.unresolved_required_inputs if x]
                missing.extend(
                    ToolPlanner._missing_required_tool_params(
                        required_params=required_params,
                        arguments=merged,
                        already_missing=missing,
                    )
                )
                return {"arguments": merged, "missing": missing}

        if tool_param_names:
            input_keys = set(step.required_inputs) | set(required_params)
            missing = [
                key
                for key in input_keys
                if key in tool_param_names
                and (candidate_args.get(key) is None or candidate_args.get(key) == "")
            ]
        else:
            missing = []
        return {"arguments": candidate_args, "missing": missing}

    @staticmethod
    def _missing_required_tool_params(
        *,
        required_params: list[str],
        arguments: dict[str, Any],
        already_missing: list[str],
    ) -> list[str]:
        missing_set = set(already_missing)
        return [
            key
            for key in required_params
            if key not in missing_set
            and (arguments.get(key) is None or arguments.get(key) == "")
        ]


class ToolExecutor(metaclass=SingletonMeta):
    """Runs tool plans with retries, fallbacks, stop policies, and parallel batches."""


    async def execute(
        self,
        *,
        plan: ToolPlan,
        runtime_args_by_tool: dict[str, dict[str, Any]],
        execution_context: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        ordered_steps = sorted(plan.tool_steps, key=lambda s: (s.priority, s.step_id))
        index_by_step_id = {step.step_id: idx for idx, step in enumerate(ordered_steps)}
        executions: list[ToolStepExecution] = []
        success_count = 0
        fail_count = 0
        skip_count = 0
        success_weight_sum = 0.0
        total_weight = sum(step.success_weight for step in ordered_steps) or 1.0
        fallback_triggered = False
        context = execution_context or {}

        for batch in self._batch_steps(ordered_steps):
            prepared: list[tuple[ToolStepPlan, dict[str, Any]]] = []
            skipped_in_batch: list[ToolStepExecution] = []

            for step in batch:
                args, missing = await self._prepare_step_arguments(
                    step, plan, runtime_args_by_tool, context
                )
                if missing:
                    skip_count += 1
                    skipped = self._record_skipped_step(step, args, missing)
                    skipped_in_batch.append(skipped)
                    self._emit_tool_done(
                        step=step,
                        args=args,
                        execution=skipped,
                        execution_context=context,
                    )
                else:
                    prepared.append((step, args))

            executions.extend(skipped_in_batch)

            if prepared:
                batch_results = await self._execute_prepared_steps(prepared, execution_context=context)
                for step, execution_result in zip(
                    [step for step, _ in prepared], batch_results, strict=True
                ):
                    executions.append(execution_result)
                    if execution_result.status == "done":
                        success_count += 1
                        success_weight_sum += step.success_weight
                    else:
                        fail_count += 1

                    if execution_result.status == "error":
                        next_index = self._next_index_for_step(step, index_by_step_id)
                        current_index = index_by_step_id[step.step_id]
                        fallback_triggered = fallback_triggered or next_index != (
                            current_index + 1
                        )
                        if step.on_failure.action == "abort_domain":
                            domain_confidence = min(1.0, success_weight_sum / total_weight)
                            return ToolExecutionResult(
                                domain=plan.domain,
                                steps=executions,
                                summary=ToolExecutionSummary(
                                    successful_steps=success_count,
                                    failed_steps=fail_count,
                                    skipped_steps=skip_count,
                                    domain_confidence=domain_confidence,
                                    fallback_triggered=fallback_triggered
                                    or (fail_count > 0 and success_count > 0),
                                ),
                            )

            if self._evaluate_stop_conditions(
                plan, success_count, success_weight_sum, total_weight
            ):
                break

        domain_confidence = min(1.0, success_weight_sum / total_weight)

        return ToolExecutionResult(
            domain=plan.domain,
            steps=executions,
            summary=ToolExecutionSummary(
                successful_steps=success_count,
                failed_steps=fail_count,
                skipped_steps=skip_count,
                domain_confidence=domain_confidence,
                fallback_triggered=fallback_triggered or (fail_count > 0 and success_count > 0),
            ),
        )

    @staticmethod
    def _batch_steps(steps: list[ToolStepPlan]) -> list[list[ToolStepPlan]]:
        """Group steps into parallel batches by priority.

        All tools at the same priority run concurrently. Lower-priority batches
        start only after the previous priority finishes.
        """
        if not steps:
            return []
        return [list(group) for _, group in groupby(steps, key=lambda s: s.priority)]

    async def _execute_prepared_steps(
        self,
        prepared: list[tuple[ToolStepPlan, dict[str, Any]]],
        *,
        execution_context: dict[str, Any],
    ) -> list[ToolStepExecution]:
        if len(prepared) == 1:
            step, args = prepared[0]
            return [
                await self._execute_step_with_retries(
                    step,
                    args,
                    execution_context=execution_context,
                )
            ]

        coros = [
            self._execute_step_with_retries(step, args, execution_context=execution_context) 
            for step, args in prepared
        ]
        
        return await asyncio.gather(*coros)

    @staticmethod
    def _next_index_for_step(
        step: ToolStepPlan,
        index_by_step_id: dict[str, int],
    ) -> int:
        current_index = index_by_step_id[step.step_id]
        return ToolExecutor._next_step_index_after_failure(
            current_index=current_index,
            step=step,
            index_by_step_id=index_by_step_id,
        )

    async def _prepare_step_arguments(
        self,
        step: ToolStepPlan,
        plan: ToolPlan,
        runtime_args_by_tool: dict[str, dict[str, Any]],
        execution_context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        merged_args = dict(step.args_template)
        merged_args.update(runtime_args_by_tool.get(step.tool_name, {}))
        resolution = await ToolPlanner.resolve_step_arguments(
            plan=plan,
            step=step,
            candidate_args=merged_args,
            execution_context=execution_context,
        )
        return resolution["arguments"], list(resolution["missing"])

    @staticmethod
    def _record_skipped_step(
        step: ToolStepPlan,
        args: dict[str, Any],
        missing: list[str],
    ) -> ToolStepExecution:
        return ToolStepExecution(
            step_id=step.step_id,
            tool_name=step.tool_name,
            status="skipped",
            attempts=0,
            latency_ms=0,
            error_type="validation_error",
            error_message=f"Missing required inputs: {', '.join(missing)}",
            input_arguments=args,
            result=None,
        )

    @staticmethod
    def _execution_time_seconds(latency_ms: int) -> float:
        return round(latency_ms / 1000.0, 3)

    @staticmethod
    def _emit_tool_running(
        *,
        step: ToolStepPlan,
        args: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> None:
        emit_event(
            DataAgentStepEvent(
                phase="running",
                tool_name=step.tool_name,
                tool_input=args,
                step_id=step.step_id,
                domain=execution_context.get("domain"),
            )
        )

    @staticmethod
    def _emit_tool_done(
        *,
        step: ToolStepPlan,
        args: dict[str, Any],
        execution: ToolStepExecution,
        execution_context: dict[str, Any],
    ) -> None:
        result = execution.result
        if execution.status == "skipped":
            observation = execution.error_message or "Step skipped."
            artifacts = ToolArtifacts()
        elif result is not None:
            observation = result.message or ""
            artifacts = result.artifacts
        else:
            observation = execution.error_message or ""
            artifacts = ToolArtifacts()

        emit_event(
            DataAgentStepEvent(
                phase="done",
                tool_name=step.tool_name,
                tool_input=args,
                step_id=step.step_id,
                domain=execution_context.get("domain"),
                status=execution.status,
                attempts=execution.attempts,
                execution_time_seconds=ToolExecutor._execution_time_seconds(
                    execution.latency_ms
                ),
                observation=observation,
                error=execution.status != "done",
                artifacts=artifacts,
            )
        )

    async def _execute_step_with_retries(
        self,
        step: ToolStepPlan,
        args: dict[str, Any],
        *,
        execution_context: dict[str, Any] | None = None,
    ) -> ToolStepExecution:
        context = execution_context or {}
        self._emit_tool_running(step=step, args=args, execution_context=context)
        attempts = 0
        last_err = ""
        last_error_type: ErrorType | None = None
        last_result: ToolResponse | None = None
        latency_ms = 0
        max_attempts = max(1, step.retry_policy.max_retries + 1)

        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            t0 = time.perf_counter()
            last_result = await MCPClient().call_mcp_tool(step.tool_name, args)
            latency_ms += int((time.perf_counter() - t0) * 1000)
            if not last_result.error:
                execution = ToolStepExecution(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    status="done",
                    attempts=attempts,
                    latency_ms=latency_ms,
                    input_arguments=args,
                    result=last_result,
                )
                self._emit_tool_done(
                    step=step,
                    args=args,
                    execution=execution,
                    execution_context=context,
                )
                return execution

            last_err = last_result.message or "Tool execution failed"
            last_error_type = self._infer_error_type(last_result, last_err)
            can_retry = (
                attempt < max_attempts
                and step.retry_policy.backoff != "none"
                and self._should_retry(last_error_type, step.retry_policy.retry_on)
            )
            if can_retry:
                delay_ms = self._compute_backoff_ms(step.retry_policy, attempt)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)

        execution = ToolStepExecution(
            step_id=step.step_id,
            tool_name=step.tool_name,
            status="error",
            attempts=attempts,
            latency_ms=latency_ms,
            error_type=last_error_type or "unknown",
            error_message=last_err,
            input_arguments=args,
            result=last_result,
        )
        self._emit_tool_done(
            step=step,
            args=args,
            execution=execution,
            execution_context=context,
        )
        return execution

    @staticmethod
    def _evaluate_stop_conditions(
        plan: ToolPlan,
        success_count: int,
        success_weight_sum: float,
        total_weight: float,
    ) -> bool:
        domain_confidence = min(1.0, success_weight_sum / total_weight)
        return ToolExecutor._should_stop(plan.stop_policy, success_count, domain_confidence)

    @staticmethod
    def _compute_backoff_ms(retry_policy: RetryPolicy, attempt: int) -> int:
        strategy = backoff_strategy_for(retry_policy.backoff)
        if strategy is None:
            return 0
        return strategy.compute_delay_ms(retry_policy.initial_delay_ms, attempt)

    @staticmethod
    def _should_retry(error_type: ErrorType | None, retry_on: list[RetryTrigger]) -> bool:
        return bool(error_type and error_type in retry_on)

    @staticmethod
    def _infer_error_type(result: ToolResponse | None, message: str) -> ErrorType:
        msg = (message or "").lower()
        if "timeout" in msg:
            return "timeout"
        if "429" in msg or "rate limit" in msg:
            return "http_429"
        if any(x in msg for x in ("500", "502", "503", "504", "server error")):
            return "http_5xx"
        if any(x in msg for x in ("connection", "network", "dns", "ssl", "refused")):
            return "network_error"
        if "missing required inputs" in msg or "validation" in msg:
            return "validation_error"
        if result is not None and not result.error and not result.data:
            return "empty_result"
        return "unknown"

    @staticmethod
    def _should_stop(stop_policy: StopPolicy, success_count: int, confidence: float) -> bool:
        if stop_policy.mode == "run_all":
            return False
        if stop_policy.mode == "stop_on_first_success":
            return success_count >= max(1, stop_policy.min_successful_steps)
        if stop_policy.mode == "stop_on_confidence":
            return confidence >= stop_policy.confidence_threshold
        return False

    @staticmethod
    def _next_step_index_after_failure(
        *,
        current_index: int,
        step: ToolStepPlan,
        index_by_step_id: dict[str, int],
    ) -> int:
        if step.on_failure.action != "fallback_to_step":
            return current_index + 1
        fallback_step_id = step.on_failure.fallback_to_step_id
        if not fallback_step_id:
            return current_index + 1
        fallback_idx = index_by_step_id.get(fallback_step_id)
        if fallback_idx is None:
            return current_index + 1
        return fallback_idx
