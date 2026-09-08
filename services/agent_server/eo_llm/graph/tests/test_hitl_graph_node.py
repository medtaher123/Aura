"""GraphNode HITL API integration with LangGraph checkpointer."""

from __future__ import annotations

import asyncio
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from eo_llm.graph import hitl as hitl_store
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, GraphStateModel, dump_state


class _EchoHitlNode(GraphNode):
    node_name = "echo_hitl"

    async def run(self, s: GraphStateModel) -> GraphState:
        await self.pause_for_hitl(
            s,
            {
                "data": {"needs_input": {"answer": {"prompt": "Provide answer"}}},
                "prompt": "Provide answer",
            },
        )
        return dump_state(s)


def test_graph_node_hitl_interrupt_and_resume() -> None:
    graph = StateGraph(GraphState)
    graph.add_node("echo_hitl", _EchoHitlNode())
    graph.set_entry_point("echo_hitl")
    graph.add_edge("echo_hitl", END)
    compiled = graph.compile(checkpointer=MemorySaver())

    thread_id = f"test:{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    async def _run() -> dict[str, object]:
        interrupted = False
        final: dict[str, object] = {}
        async for chunk in compiled.astream(
            {"query": "hello", "user_query": "hello"},
            config=config,
            stream_mode="values",
        ):
            if isinstance(chunk, dict):
                final = {k: v for k, v in chunk.items() if k != "__interrupt__"}
                interrupted = bool(chunk.get("__interrupt__"))
        assert interrupted
        attachments = [
            {
                "type": "location",
                "name": "world",
                "coordinates": [1.0, 2.0],
            }
        ]
        with hitl_store.hitl_resume_context(
            {},
            attachments=attachments,
            thread_id=thread_id,
        ):
            async for chunk in compiled.astream(
                Command(resume={"data": {"attachments": attachments}}),
                config=config,
                stream_mode="values",
            ):
                if isinstance(chunk, dict):
                    final = {k: v for k, v in chunk.items() if k != "__interrupt__"}
        return final

    final = asyncio.run(_run())
    resolved = final.get("resolved_location") or {}
    assert resolved.get("display_name") == "world"
    assert resolved.get("lat") == 1.0
    assert resolved.get("lon") == 2.0
