"""Router node: executes orchestrator-selected domain routing."""

from __future__ import annotations

from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, dump_state, GraphStateModel


class RouterNode(GraphNode):
    node_name = "router"
    status_stage = "planning"
    status_message = "Selecting domains..."

    def run(self, s: GraphStateModel) -> GraphState:
        # Routing is owned by the orchestrator / Bedrock LLM policy layer.
        # Router only dispatches based on pre-computed selected_domains.
        s.next_step = "run_domains" if s.selected_domains else "websearch_only"
        return dump_state(s)


router_node = RouterNode()
