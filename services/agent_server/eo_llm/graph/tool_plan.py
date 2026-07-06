"""Domain tool planning and execution models and services."""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.graph.backoff import backoff_strategy_for
from eo_llm.prompts import get_arg_resolver_prompt, get_tool_planner_prompt

if TYPE_CHECKING:
    from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter

DomainName = Literal[
    "flood_damage",
    "fire_detection",
    "disaster_detection",
    "infrastructure",
    "stac",
]
ToolName = Literal[
    "geoserver_risk_mask_tool",
    "flood_damage_city_tool",
    "flood_depth_damage_tool",
    "streamflow_forecast_tool",
    "estimate_surface_water_ingress_tool",
    "detect_fire_tool",
    "clms_burnt_area_impact_tool",
    "query_disaster_events_tool",
    "clms_land_cover_exposure_tool",
    "cems_rapid_mapping_events_tool",
    "infrastructure_query_tool",
    "get_route_info",
    "query_stac_catalog",
    "maxar_open_data_imagery_tool",
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

    max_retries: int = Field(default=1, ge=0, le=5)
    backoff: BackoffMode = "fixed"
    initial_delay_ms: int = Field(default=300, ge=0)
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
    confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    min_successful_steps: int = Field(default=1, ge=1)


class ToolStepPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    tool_name: ToolName
    priority: int = Field(ge=1)
    required_inputs: list[str] = Field(default_factory=list)
    parallel_group: str | None = None
    args_template: dict[str, Any] = Field(default_factory=dict)
    retry_policy: RetryPolicy
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    on_failure: OnFailurePolicy
    success_weight: float = Field(default=0.2, ge=0.0, le=1.0)


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
    result: dict[str, Any] | None = None


class ToolExecutionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successful_steps: int = Field(default=0, ge=0)
    failed_steps: int = Field(default=0, ge=0)
    skipped_steps: int = Field(default=0, ge=0)
    domain_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
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


class ToolIntrospector:
    """Fetches and caches MCP tool parameter metadata."""

    def __init__(self, cache: dict[str, dict[str, Any]] | None = None) -> None:
        self._cache = cache if cache is not None else {}

    def get_metadata(self, tool_name: str) -> dict[str, Any]:
        cached = self._cache.get(tool_name)
        if cached is not None:
            return cached

        meta: dict[str, Any] = {
            "all_params": [],
            "required_params": [],
            "docstring": "",
        }

        try:
            from eo_llm.adapters.mcp_client import get_tool_metadata

            fetched = get_tool_metadata(tool_name)
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
        adapter: AgentCoreAdapter,
        domain: str,
        allowed_tools: list[str],
        introspector: ToolIntrospector | None = None,
    ) -> None:
        self._adapter = adapter
        self._domain = domain
        self._allowed_tools = allowed_tools
        self._introspector = introspector or ToolIntrospector()

    def select_tool_plan(self, query: str) -> ToolPlan:
        if (
            self._adapter.is_ready()
            and self._adapter.structured_client is not None
            and self._adapter._tool_planner_model_id
            and self._allowed_tools
        ):
            system_prompt, user_prompt = get_tool_planner_prompt(
                domain=self._domain,
                query=query,
                allowed_tools=self._allowed_tools,
            )
            candidate = self._adapter.structured_client.call_structured(
                model_id=self._adapter._tool_planner_model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=ToolPlan,
                schema_name="domain_tool_plan",
                schema_description="Execution plan for a single EO_LLM domain agent",
                max_tokens=1200,
            )
            if candidate is not None:
                if candidate.domain == self._domain and all(
                    step.tool_name in self._allowed_tools for step in candidate.tool_steps
                ):
                    return candidate
                raise RuntimeError(
                    f"select_tool_plan returned invalid domain/tools for {self._domain}."
                )

            raise RuntimeError(
                "select_tool_plan Bedrock call returned no valid schema output "
                f"for {self._domain}. Reason: "
                f"{self._adapter._last_bedrock_failure_reason or 'unknown'}"
            )

        raise RuntimeError(
            f"select_tool_plan unavailable for {self._domain}: "
            "Bedrock client/model not ready."
        )

    def resolve_step_arguments(
        self,
        *,
        plan: ToolPlan,
        step: ToolStepPlan,
        candidate_args: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        tool_meta = self._introspector.get_metadata(step.tool_name)
        tool_param_names = list(tool_meta.get("all_params") or [])
        required_params = list(tool_meta.get("required_params") or [])
        docstring = str(tool_meta.get("docstring") or "")

        if (
            self._adapter.is_ready()
            and self._adapter.structured_client is not None
            and self._adapter._tool_planner_model_id
            and tool_param_names
        ):
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
            parsed = self._adapter.structured_client.call_structured(
                model_id=self._adapter._tool_planner_model_id,
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
                return {"arguments": merged, "missing": missing}

        if tool_param_names:
            missing = [
                key
                for key in step.required_inputs
                if key in tool_param_names
                and (candidate_args.get(key) is None or candidate_args.get(key) == "")
            ]
        else:
            missing = []
        return {"arguments": candidate_args, "missing": missing}


class ToolExecutor:
    """Runs tool plans with retries, fallbacks, and stop policies."""

    def __init__(
        self,
        tool_caller: Callable[[str, dict[str, Any]], dict[str, Any]],
        planner: ToolPlanner,
    ) -> None:
        self._tool_caller = tool_caller
        self._planner = planner

    def execute(
        self,
        *,
        plan: ToolPlan,
        runtime_args_by_tool: dict[str, dict[str, Any]],
        execution_context: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        ordered_steps = sorted(plan.tool_steps, key=lambda s: s.priority)
        index_by_step_id = {step.step_id: idx for idx, step in enumerate(ordered_steps)}
        executions: list[ToolStepExecution] = []
        success_count = 0
        fail_count = 0
        skip_count = 0
        success_weight_sum = 0.0
        total_weight = sum(step.success_weight for step in ordered_steps) or 1.0
        fallback_triggered = False
        context = execution_context or {}

        i = 0
        while i < len(ordered_steps):
            step = ordered_steps[i]

            args, missing = self._prepare_step_arguments(
                step, plan, runtime_args_by_tool, context
            )
            if missing:
                skip_count += 1
                executions.append(self._record_skipped_step(step, args, missing))
                i = self._get_next_index(i, step, index_by_step_id)
                continue

            execution_result = self._execute_step_with_retries(step, args)
            executions.append(execution_result)
            if execution_result.status == "done":
                success_count += 1
                success_weight_sum += step.success_weight
            else:
                fail_count += 1

            if self._evaluate_stop_conditions(
                plan, success_count, success_weight_sum, total_weight
            ):
                break

            if execution_result.status == "error":
                next_index = self._get_next_index(i, step, index_by_step_id)
                fallback_triggered = fallback_triggered or next_index != (i + 1)
                if step.on_failure.action == "abort_domain":
                    break
                i = next_index
                continue

            i += 1

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

    def _prepare_step_arguments(
        self,
        step: ToolStepPlan,
        plan: ToolPlan,
        runtime_args_by_tool: dict[str, dict[str, Any]],
        execution_context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        merged_args = dict(step.args_template)
        merged_args.update(runtime_args_by_tool.get(step.tool_name, {}))
        resolution = self._planner.resolve_step_arguments(
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

    def _execute_step_with_retries(
        self,
        step: ToolStepPlan,
        args: dict[str, Any],
    ) -> ToolStepExecution:
        attempts = 0
        last_err = ""
        last_error_type: ErrorType | None = None
        last_result: dict[str, Any] | None = None
        latency_ms = 0
        max_attempts = max(1, step.retry_policy.max_retries + 1)

        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            t0 = time.perf_counter()
            last_result = self._tool_caller(step.tool_name, args)
            latency_ms += int((time.perf_counter() - t0) * 1000)
            if not bool(last_result.get("error")):
                return ToolStepExecution(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    status="done",
                    attempts=attempts,
                    latency_ms=latency_ms,
                    input_arguments=args,
                    result=last_result,
                )

            last_err = str(last_result.get("message") or "Tool execution failed")
            last_error_type = self._infer_error_type(last_result, last_err)
            can_retry = (
                attempt < max_attempts
                and step.retry_policy.backoff != "none"
                and self._should_retry(last_error_type, step.retry_policy.retry_on)
            )
            if can_retry:
                delay_ms = self._compute_backoff_ms(step.retry_policy, attempt)
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)

        return ToolStepExecution(
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
    def _get_next_index(
        current_index: int,
        step: ToolStepPlan,
        index_by_step_id: dict[str, int],
    ) -> int:
        return ToolExecutor._next_step_index_after_failure(
            current_index=current_index,
            step=step,
            index_by_step_id=index_by_step_id,
        )

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
    def _infer_error_type(result: dict[str, Any] | None, message: str) -> ErrorType:
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
        if result is not None and not result.get("error") and not result.get("data"):
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
