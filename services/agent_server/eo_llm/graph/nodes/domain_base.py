"""Base classes for domain graph nodes."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, ClassVar

from eo_llm.adapters.bedrock import BedrockLLMAdapter
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.nodes.helpers import LocationContext, wrap_domain_result
from eo_llm.graph.state import GraphState, GraphStateModel
from eo_llm.graph.tool_plan import (
    ToolExecutionResult,
    ToolExecutor,
    ToolIntrospector,
    ToolName,
    ToolPlan,
    ToolPlanner,
)


class DomainNode(GraphNode):
    """Base for nodes that write into ``domain_results``."""

    domain_name: ClassVar[str]
    status_stage = "tool_call"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.node_name and getattr(cls, "domain_name", ""):
            cls.node_name = cls.domain_name
        if cls.node_name:
            GraphNode._registry[cls.node_name] = cls

    def is_selected(self, s: GraphStateModel) -> bool:
        return self.domain_name in set(s.selected_domains)

    def run(self, s: GraphStateModel) -> GraphState:
        if not self.is_selected(s):
            return {}
        return self.execute(s)

    @abstractmethod
    def execute(self, s: GraphStateModel) -> GraphState: ...


class ToolPlanDomainNode(DomainNode):
    """Domain node that plans and executes MCP tools via Bedrock LLM."""

    tools: ClassVar[list[ToolName]]
    requires_location: bool = True
    _tools_registry: ClassVar[dict[str, list[str]]] = {}

    def __init__(
        self,
        adapter: BedrockLLMAdapter | None = None,
        tool_caller: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        *,
        introspector: ToolIntrospector | None = None,
        planner: ToolPlanner | None = None,
        executor: ToolExecutor | None = None,
    ) -> None:
        super().__init__(adapter=adapter, tool_caller=tool_caller)
        if planner is None:
            introspector = introspector or ToolIntrospector()
            planner = ToolPlanner(
                adapter=self._adapter,
                domain=self.domain_name,
                allowed_tools=list(self.tools),
                introspector=introspector,
            )
        if executor is None:
            executor = ToolExecutor(tool_caller=self._tool_caller, planner=planner)
        self._planner = planner
        self._executor = executor

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.domain_name and getattr(cls, "tools", None):
            ToolPlanDomainNode._tools_registry[cls.domain_name] = list(cls.tools)

    @classmethod
    def tools_for(cls, domain: str) -> list[str]:
        return list(cls._tools_registry.get(domain, []))

    @abstractmethod
    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]: ...

    def select_tool_plan(self, query: str) -> ToolPlan:
        return self._planner.select_tool_plan(query)

    def execute_tool_plan(
        self,
        *,
        plan: ToolPlan,
        runtime_args_by_tool: dict[str, dict[str, Any]],
        execution_context: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        return self._executor.execute(
            plan=plan,
            runtime_args_by_tool=runtime_args_by_tool,
            execution_context=execution_context,
        )

    @property
    def missing_location_message(self) -> str:
        return f"Missing resolved lat/lon; {self.domain_name} tools not called."

    def execute(self, s: GraphStateModel) -> GraphState:
        ctx = LocationContext.from_state(s)
        if self.requires_location and not ctx.has_coordinates:
            return wrap_domain_result(
                self.domain_name,
                self._skipped_result(ctx),
            )

        runtime_args = self.build_runtime_args(ctx)
        try:
            plan = self.select_tool_plan(s.query)
            execution = self.execute_tool_plan(
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
            "result": final_step.result if final_step else {},
            "plan": plan.model_dump(mode="python"),
            "executions": [step.model_dump(mode="python") for step in execution.steps],
            "summary": execution.summary.model_dump(mode="python"),
        }


