"""Gateway node: normalizes incoming state."""

from __future__ import annotations

from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, dump_state, GraphStateModel


class GatewayNode(GraphNode):
    node_name = "gateway"

    async def run(self, s: GraphStateModel) -> GraphState:
        return dump_state(s)


gateway_node = GatewayNode()
