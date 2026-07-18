"""Aggregator node: merges domain outputs and sets next step."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.evidence_digest import build_domain_evidence_digest
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, dump_state, GraphStateModel


def _domain_result_as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        return dump(mode="python")
    return {}


class AggregatorNode(GraphNode):
    node_name = "aggregator"
    status_stage = "analyzing"
    status_message = "Aggregating evidence..."

    def run(self, s: GraphStateModel) -> GraphState:
        domain_results = dict(s.domain_results)
        web_results = list(s.web_results)

        has_domain_data = False
        for result in domain_results.values():
            result = _domain_result_as_dict(result)
            if not result:
                continue
            summary = result.get("summary")
            successful_steps = (
                summary.get("successful_steps")
                if isinstance(summary, dict)
                else None
            )
            if isinstance(successful_steps, int) and successful_steps > 0:
                has_domain_data = True
                break
            if result.get("status") == "done":
                has_domain_data = True
                break
        has_web_data = bool(web_results)
        domain_digest = build_domain_evidence_digest(domain_results)

        if has_domain_data and has_web_data:
            s.answer_source = "hybrid"
            s.confidence = 0.85
            s.can_answer = True
            s.fallback_to_websearch = False
            s.aggregated_evidence = f"{domain_digest}\n\nWeb evidence also available."
            s.next_step = "finalize"
            return dump_state(s)

        if has_domain_data:
            s.answer_source = "domain_tools"
            s.confidence = 0.75
            s.can_answer = True
            s.fallback_to_websearch = False
            s.aggregated_evidence = domain_digest
            s.next_step = "finalize"
            return dump_state(s)

        if has_web_data:
            s.answer_source = "web_search"
            s.confidence = 0.7
            s.can_answer = True
            s.fallback_to_websearch = False
            s.aggregated_evidence = "Web evidence available."
            s.next_step = "finalize"
            return dump_state(s)

        # Domain nodes ran but produced no usable tool success — try AgentCore Browser fallback.
        if domain_results and not has_domain_data:
            s.can_answer = False
            s.confidence = 0.0
            s.fallback_to_websearch = True
            s.aggregated_evidence = (
                "Domain tools ran but did not return adequate evidence; attempting web fallback."
            )
            s.next_step = "web_search"
            return dump_state(s)

        s.can_answer = False
        s.confidence = 0.0
        s.fallback_to_websearch = True
        s.aggregated_evidence = "No domain evidence yet."
        s.next_step = "web_search"
        return dump_state(s)


aggregator_node = AggregatorNode()
