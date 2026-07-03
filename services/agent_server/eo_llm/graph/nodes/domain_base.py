"""Base classes for domain graph nodes."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.nodes.helpers import LocationContext, wrap_domain_result
from eo_llm.graph.state import GraphState, GraphStateModel


class DomainNode(GraphNode):
    """Base for nodes that write into ``domain_results``."""

    @property
    @abstractmethod
    def domain_name(self) -> str: ...

    def is_selected(self, s: GraphStateModel) -> bool:
        return self.domain_name in set(s.selected_domains)

    def run(self, s: GraphStateModel) -> GraphState:
        if not self.is_selected(s):
            return {}
        return self.execute(s)

    @abstractmethod
    def execute(self, s: GraphStateModel) -> GraphState: ...


class ToolPlanDomainNode(DomainNode):
    """Domain node that plans and executes MCP tools via AgentCore."""

    requires_location: bool = True

    @abstractmethod
    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]: ...

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
            plan = self._adapter.select_tool_plan(domain=self.domain_name, query=s.query)
            execution = self._adapter.execute_tool_plan(
                plan=plan,
                runtime_args_by_tool=runtime_args,
                tool_caller=self._tool_caller,
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
        plan: AgentCoreAdapter.ToolPlan,
        execution: AgentCoreAdapter.ToolExecutionResult,
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


