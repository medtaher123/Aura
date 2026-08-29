"""Base classes for domain graph nodes."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
from eo_llm.graph.domain_agent import DomainAgentRunResult, DomainToolAgent
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.nodes.helpers import LocationContext, wrap_domain_result
from eo_llm.graph.state import GraphState, GraphStateModel
from eo_llm.graph.tool_plan import (
    ToolExecutionResult,
    ToolExecutor,
    ToolName,
    ToolPlan,
    ToolPlanner,
)
from eo_llm.prompts import get_domain_agent_prompt
from src.tools.filtering.agent_filter import (
    get_cached_agent_profile,
    resolve_allowed_tools,
)
from src.user_inputs import (
    BoundingBoxRequest,
    InputKind,
    LocationRequest,
    UserInputRequest,
    UserInputRouter,
)


@dataclass(frozen=True)
class DomainTool:
    """One MCP tool available to a domain, with optional required user inputs."""

    name: ToolName
    required_user_inputs: tuple[InputKind, ...] = ()


def _as_domain_tool(entry: ToolName | DomainTool) -> DomainTool:
    if isinstance(entry, DomainTool):
        return entry
    return DomainTool(name=entry)


class DomainNode(GraphNode):
    """Base for nodes that write into ``domain_results``."""

    domain_name: ClassVar[str]
    status_stage = "Domain_call"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.node_name and getattr(cls, "domain_name", ""):
            cls.node_name = cls.domain_name
        if cls.node_name:
            GraphNode._registry[cls.node_name] = cls

    def is_selected(self, s: GraphStateModel) -> bool:
        return self.domain_name in set(s.selected_domains)

    async def run(self, s: GraphStateModel) -> GraphState:
        if not self.is_selected(s):
            return {}
        return await self.execute(s)

    @abstractmethod
    async def execute(self, s: GraphStateModel) -> GraphState: ...


class DomainToolsNode(DomainNode):
    """Domain node with a shared tool catalog (used by plan-based and agentic nodes)."""

    shared_tools: ClassVar[list[ToolName]] = ["web_search_tool"]
    tools: ClassVar[list[ToolName | DomainTool]]
    _tools_registry: ClassVar[dict[str, list[str]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        domain_name = getattr(cls, "domain_name", None)
        tools = getattr(cls, "tools", None)
        if domain_name and tools is not None:
            DomainToolsNode._tools_registry[domain_name] = cls.resolved_tools()

    @classmethod
    def tool_specs(cls) -> dict[str, DomainTool]:
        specs: dict[str, DomainTool] = {}
        for entry in cls.tools:
            spec = _as_domain_tool(entry)
            specs[spec.name] = spec
        return specs

    @classmethod
    def resolved_tools(cls) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for entry in [*cls.shared_tools, *cls.tools]:
            name = entry if isinstance(entry, str) else entry.name
            if name in seen:
                continue
            seen.add(name)
            out.append(name)
        allowed = resolve_allowed_tools(out, get_cached_agent_profile())
        try:
            from src.tools.runtime.gateway import get_tool_gateway

            registry = get_tool_gateway().registry
            available = {d.name for d in registry.list_descriptors()}
            if available:
                allowed = [name for name in allowed if name in available]
        except Exception:
            pass
        return allowed

    @classmethod
    def tools_for(cls, domain: str) -> list[str]:
        return list(cls._tools_registry.get(domain, []))

    def user_input_satisfied(self, kind: InputKind, s: GraphStateModel) -> bool:
        if kind == "bounding_box":
            return s.resolved_area is not None
        if kind == "location":
            return bool(s.has_resolved_location)
        return False

    def build_user_input_request(
        self,
        kind: InputKind,
        s: GraphStateModel,
        ctx: LocationContext,
    ) -> UserInputRequest:
        if kind == "bounding_box":
            map_center: list[float] | None = None
            if ctx.lat is not None and ctx.lon is not None:
                map_center = [float(ctx.lat), float(ctx.lon)]
            return BoundingBoxRequest(
                prompt=(
                    "Please draw a bounding box on the map for the flood damage "
                    "analysis area."
                ),
                map_center=map_center,
                map_zoom=10.0 if map_center else None,
            )
        if kind == "location":
            return LocationRequest.from_candidates(
                list(s.location_candidates or []),
                prompt="Please confirm the location to continue.",
                location_query=s.location_query or None,
            )
        raise ValueError(f"Unsupported input kind: {kind!r}")

    def build_shared_runtime_args(
        self,
        s: GraphStateModel,
        _ctx: LocationContext,
    ) -> dict[str, dict[str, Any]]:
        return {}


class AgenticDomainNode(DomainToolsNode):
    """Domain node that iterates with the LLM until tools produce a final answer."""

    max_tool_rounds: ClassVar[int] = 8

    def __init__(self) -> None:
        super().__init__()
        self._agent = DomainToolAgent(max_rounds=self.max_tool_rounds)

    def build_system_prompt(self, s: GraphStateModel, ctx: LocationContext) -> str:
        return get_domain_agent_prompt(
            domain=self.domain_name,
            allowed_tools=self.resolved_tools(),
        )

    @abstractmethod
    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]: ...

    def serialize_hitl_blob(
        self,
        s: GraphStateModel,
        *,
        tool_call_records: list[AgentToolCallRecord] | None = None,
    ) -> dict[str, Any]:
        records = tool_call_records or []
        return {
            "tool_call_records": [
                record.model_dump(mode="python") for record in records
            ],
        }

    @staticmethod
    def _records_from_blob(blob: dict[str, Any]) -> list[AgentToolCallRecord]:
        raw = blob.get("tool_call_records")
        if not isinstance(raw, list):
            return []
        out: list[AgentToolCallRecord] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(AgentToolCallRecord.model_validate(item))
        return out

    async def execute(self, s: GraphStateModel) -> GraphState:
        blob = self.load_hitl_blob()
        tool_call_records = self._records_from_blob(blob) if blob else []

        while True:
            ctx = LocationContext.from_state(s)
            runtime_args = {
                **self.build_shared_runtime_args(s, ctx),
                **self.build_runtime_args(ctx),
            }
            try:
                run = await self._agent.run(
                    domain=self.domain_name,
                    allowed_tools=self.resolved_tools(),
                    system_prompt=self.build_system_prompt(s, ctx),
                    runtime_args_by_tool=runtime_args,
                    execution_context={
                        "query": s.query,
                        "domain": self.domain_name,
                        "resolved_location": ctx.resolved,
                    },
                    tool_call_records=tool_call_records,
                )
            except Exception as exc:
                return wrap_domain_result(
                    self.domain_name,
                    self._error_result(ctx, exc),
                )

            if not run.paused or not run.needs_input:
                return wrap_domain_result(
                    self.domain_name,
                    self._success_result(ctx, run),
                )

            needs_input = UserInputRouter.requests_to_dict(
                UserInputRouter.requests_from_dict(run.needs_input)
            )
            s = await self.pause_for_hitl(
                s,
                {
                    "data": {"needs_input": needs_input},
                    "prompt": run.message or "Additional input required.",
                },
                blob=self.serialize_hitl_blob(
                    s, tool_call_records=run.tool_calls
                ),
            )
            tool_call_records = list(run.tool_calls)

    def _error_result(self, ctx: LocationContext, exc: Exception) -> dict[str, Any]:
        return {
            "status": "error",
            "resolved_location": ctx.resolved,
            "message": f"Agentic domain execution failed: {exc}",
            "error": True,
        }

    def _success_result(
        self,
        ctx: LocationContext,
        run: DomainAgentRunResult,
    ) -> dict[str, Any]:
        last_call = run.tool_calls[-1] if run.tool_calls else None
        return {
            "status": "done" if not run.error else "error",
            "resolved_location": ctx.resolved,
            "message": run.message,
            "tool": last_call.tool_name if last_call else None,
            "result": (
                last_call.result.model_dump(mode="python")
                if last_call and last_call.result
                else {}
            ),
            "tool_calls": [call.model_dump(mode="python") for call in run.tool_calls],
            "error": run.error,
        }


class ToolPlanDomainNode(DomainToolsNode):
    """Domain node that plans and executes MCP tools via Bedrock LLM."""

    def __init__(
        self,
        planner: ToolPlanner | None = None,
    ) -> None:
        super().__init__()
        self._executor = ToolExecutor()

    def serialize_hitl_blob(
        self,
        s: GraphStateModel,
        *,
        plan: ToolPlan | None = None,
    ) -> dict[str, Any]:
        return {
            "plan": plan.model_dump(mode="python") if plan is not None else None,
        }

    @staticmethod
    def _plan_from_blob(blob: dict[str, Any]) -> ToolPlan | None:
        raw = blob.get("plan")
        if isinstance(raw, dict) and raw:
            return ToolPlan.model_validate(raw)
        return None

    def missing_user_inputs(
        self,
        plan: ToolPlan,
        s: GraphStateModel,
        ctx: LocationContext,
    ) -> dict[InputKind, UserInputRequest]:
        specs = self.tool_specs()
        missing: dict[InputKind, UserInputRequest] = {}
        for step in plan.tool_steps:
            spec = specs.get(step.tool_name)
            if spec is None:
                continue
            for kind in spec.required_user_inputs:
                if kind in missing:
                    continue
                if self.user_input_satisfied(kind, s):
                    continue
                missing[kind] = self.build_user_input_request(kind, s, ctx)
        return missing

    @abstractmethod
    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]: ...

    async def select_tool_plan(self, query: str) -> ToolPlan:
        return await ToolPlanner(
            domain=self.domain_name, allowed_tools=self.resolved_tools()
        ).select_tool_plan(query)

    async def execute_tool_plan(
        self,
        *,
        plan: ToolPlan,
        runtime_args_by_tool: dict[str, dict[str, Any]],
        execution_context: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        return await self._executor.execute(
            plan=plan,
            runtime_args_by_tool=runtime_args_by_tool,
            execution_context=execution_context,
        )

    async def execute(self, s: GraphStateModel) -> GraphState:
        blob = self.load_hitl_blob()
        ctx = LocationContext.from_state(s)
        runtime_args = {
            **self.build_shared_runtime_args(s, ctx),
            **self.build_runtime_args(ctx),
        }

        try:
            plan = self._plan_from_blob(blob) if blob else None
            if plan is None:
                plan = await self.select_tool_plan(s.query)

            missing = self.missing_user_inputs(plan, s, ctx)
            if missing:
                needs_input = UserInputRouter.requests_to_dict(missing)
                prompt_parts = [
                    str(req.prompt)
                    for req in missing.values()
                    if getattr(req, "prompt", None)
                ]
                prompt = " ".join(prompt_parts) if prompt_parts else (
                    "Please provide the requested input to continue."
                )
                s = await self.pause_for_hitl(
                    s,
                    {
                        "data": {"needs_input": needs_input},
                        "prompt": prompt,
                    },
                    blob=self.serialize_hitl_blob(s, plan=plan),
                )
                ctx = LocationContext.from_state(s)
                runtime_args = {
                    **self.build_shared_runtime_args(s, ctx),
                    **self.build_runtime_args(ctx),
                }
                missing = self.missing_user_inputs(plan, s, ctx)
                if missing:
                    raise RuntimeError("Required user inputs still missing after HITL resume")

            execution = await self.execute_tool_plan(
                plan=plan,
                runtime_args_by_tool=runtime_args,
                execution_context={
                    "query": s.query,
                    "domain": self.domain_name,
                    "resolved_location": ctx.resolved,
                },
            )
        except Exception as exc:
            return wrap_domain_result(
                self.domain_name,
                self._error_result(ctx, exc),
            )

        return wrap_domain_result(
            self.domain_name,
            self._success_result(ctx, plan, execution),
        )

    def _error_result(self, ctx: LocationContext, exc: Exception) -> dict[str, Any]:
        return {
            "status": "error",
            "resolved_location": ctx.resolved,
            "message": f"Tool planning/execution failed: {exc}",
            "summary": {"successful_steps": 0},
            "error": True,
        }

    def _success_result(
        self,
        ctx: LocationContext,
        plan: ToolPlan,
        execution: ToolExecutionResult,
    ) -> dict[str, Any]:
        successful = [
            step for step in execution.steps if step.status == "done" and step.result
        ]
        final_step = successful[-1] if successful else None
        return {
            "status": "done" if execution.summary.successful_steps > 0 else "error",
            "resolved_location": ctx.resolved,
            "tool": final_step.tool_name if final_step else None,
            "arguments": final_step.input_arguments if final_step else {},
            "result": (
                final_step.result.model_dump(mode="python")
                if final_step and final_step.result
                else {}
            ),
            "plan": plan.model_dump(mode="python"),
            "executions": [step.model_dump(mode="python") for step in execution.steps],
            "summary": execution.summary.model_dump(mode="python"),
        }
