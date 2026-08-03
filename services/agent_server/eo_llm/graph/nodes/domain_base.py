"""Base classes for domain graph nodes."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.nodes.helpers import LocationContext, wrap_domain_result
from eo_llm.graph.state import GraphState, GraphStateModel, dump_state
from eo_llm.graph.tool_plan import (
    ToolExecutionResult,
    ToolExecutor,
    ToolName,
    ToolPlan,
    ToolPlanner,
)
from src.schemas.user_inputs import (
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


class ToolPlanDomainNode(DomainNode):
    """Domain node that plans and executes MCP tools via Bedrock LLM.

    ``shared_tools`` are available to every domain; ``tools`` are domain-specific.
    The planner/executor always see ``shared_tools + tools`` (deduped).
    Entries in ``tools`` may be plain tool names or ``DomainTool`` specs that
    declare ``required_user_inputs``.
    """

    shared_tools: ClassVar[list[ToolName]] = ["web_search_tool"]
    tools: ClassVar[list[ToolName | DomainTool]]
    requires_location: bool = True
    _tools_registry: ClassVar[dict[str, list[str]]] = {}

    def __init__(
        self,
        planner: ToolPlanner | None = None,
    ) -> None:
        super().__init__()
        planner = ToolPlanner(
            domain=self.domain_name,
            allowed_tools=self.resolved_tools(),
        )
        self._executor = ToolExecutor()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.domain_name and getattr(cls, "tools", None) is not None:
            ToolPlanDomainNode._tools_registry[cls.domain_name] = cls.resolved_tools()

    @classmethod
    def tool_specs(cls) -> dict[str, DomainTool]:
        """Map tool name → ``DomainTool`` for this domain (domain tools only)."""
        specs: dict[str, DomainTool] = {}
        for entry in cls.tools:
            spec = _as_domain_tool(entry)
            specs[spec.name] = spec
        return specs

    @classmethod
    def resolved_tools(cls) -> list[str]:
        """Shared tools first, then domain tools (order preserved, duplicates dropped)."""
        seen: set[str] = set()
        out: list[str] = []
        for entry in [*cls.shared_tools, *cls.tools]:
            name = entry if isinstance(entry, str) else entry.name
            if name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out

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

    def missing_user_inputs(
        self,
        plan: ToolPlan,
        s: GraphStateModel,
        ctx: LocationContext,
    ) -> dict[InputKind, UserInputRequest]:
        """Required user inputs for tools in ``plan`` that are not yet on state."""
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

    def build_shared_runtime_args(
        self,
        s: GraphStateModel,
        _ctx: LocationContext,
    ) -> dict[str, dict[str, Any]]:
        return {}

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

    @property
    def missing_location_message(self) -> str:
        return f"Missing resolved lat/lon; {self.domain_name} tools not called."

    def _pause_for_user_inputs(
        self,
        s: GraphStateModel,
        ctx: LocationContext,
        plan: ToolPlan,
        missing: dict[InputKind, UserInputRequest],
    ) -> GraphState:
        needs_input = UserInputRouter.requests_to_dict(missing)
        prompt_parts = [req.llm_text() for req in missing.values()]
        prompt = " ".join(prompt_parts) if prompt_parts else (
            "Please provide the requested input to continue."
        )
        s.needs_input = needs_input
        s.stopped_for_user_input = True
        s.final_answer = prompt
        s.answer_source = "domain_tools"
        out = dump_state(s)
        out["domain_results"] = {
            self.domain_name: {
                "status": "paused",
                "resolved_location": ctx.resolved,
                "plan": plan.model_dump(mode="python"),
                "message": prompt,
                "error": False,
            }
        }
        return out

    async def execute(self, s: GraphStateModel) -> GraphState:
        ctx = LocationContext.from_state(s)
        if self.requires_location and not ctx.has_coordinates:
            return wrap_domain_result(
                self.domain_name,
                self._skipped_result(ctx),
            )

        runtime_args = {
            **self.build_shared_runtime_args(s, ctx),
            **self.build_runtime_args(ctx),
        }
        try:
            plan = await self.select_tool_plan(s.query)
            missing = self.missing_user_inputs(plan, s, ctx)
            if missing:
                return self._pause_for_user_inputs(s, ctx, plan, missing)
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

    def _skipped_result(self, ctx: LocationContext) -> dict[str, Any]:
        return {
            "status": "skipped",
            "resolved_location": ctx.resolved or {},
            "message": self.missing_location_message,
            "error": True,
        }

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
