"""Tests for HITL pause/resume storage helpers."""

from __future__ import annotations

import asyncio
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from eo_llm.graph import hitl as hitl_store
from eo_llm.graph.hitl import state_update_from_attachments
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, GraphStateModel, dump_state


def test_register_and_take_pause_blobs() -> None:
    thread_id = "test-pause"
    hitl_store.register_pause_blob(
        "fire_detection", {"tool_call_records": []}, thread_id=thread_id
    )
    hitl_store.register_pause_blob(
        "location_gate", {"location_query": "Paris"}, thread_id=thread_id
    )
    blobs = hitl_store.take_pause_blobs(thread_id)
    assert blobs["fire_detection"] == {"tool_call_records": []}
    assert blobs["location_gate"] == {"location_query": "Paris"}
    assert hitl_store.take_pause_blobs(thread_id) == {}


def test_resume_context_exposes_blobs() -> None:
    thread_id = "test-resume"
    with hitl_store.hitl_resume_context(
        {"agentic_test": {"tool_call_records": [{"tool_name": "x"}]}},
        thread_id=thread_id,
    ):
        assert hitl_store.get_resume_blob("agentic_test", thread_id=thread_id) == {
            "tool_call_records": [{"tool_name": "x"}]
        }
    assert hitl_store.get_resume_blob("agentic_test", thread_id=thread_id) is None


def test_state_update_from_location_attachment_and_blob() -> None:
    patch = state_update_from_attachments(
        [
            {
                "type": "location",
                "name": "Paris, France",
                "coordinates": [48.8566, 2.3522],
            }
        ],
        {
            "location_gate": {
                "location_query": "Paris",
                "location_candidates": [
                    {
                        "display_name": "Paris, France",
                        "lat": 48.8566,
                        "lon": 2.3522,
                    },
                    {
                        "display_name": "Paris, Texas, USA",
                        "lat": 33.6609,
                        "lon": -95.5555,
                    },
                ],
            }
        },
    )
    resolved = patch.get("resolved_location") or {}
    assert resolved.get("display_name") == "Paris, France"
    assert patch.get("location_query") == "Paris"
    assert len(patch.get("location_candidates") or []) == 2


def test_pause_blobs_visible_to_parent_after_langgraph_interrupt() -> None:
    """Blobs registered inside a node must be readable by the astream parent."""

    class _PauseNode(GraphNode):
        node_name = "pause_blob_node"

        async def run(self, s: GraphStateModel) -> GraphState:
            await self.pause_for_hitl(
                s,
                {
                    "data": {"needs_input": {"answer": {"prompt": "Provide answer"}}},
                    "prompt": "Provide answer",
                },
                blob={"tool_call_records": [{"tool_name": "x"}]},
            )
            return dump_state(s)

    graph = StateGraph(GraphState)
    graph.add_node("pause_blob_node", _PauseNode())
    graph.set_entry_point("pause_blob_node")
    graph.add_edge("pause_blob_node", END)
    compiled = graph.compile(checkpointer=MemorySaver())
    thread_id = f"blob-test:{uuid.uuid4()}"

    async def _run() -> dict[str, dict]:
        interrupted = False
        async for chunk in compiled.astream(
            {"query": "hello", "user_query": "hello"},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="values",
        ):
            if isinstance(chunk, dict) and chunk.get("__interrupt__"):
                interrupted = True
        assert interrupted
        return hitl_store.take_pause_blobs(thread_id)

    blobs = asyncio.run(_run())
    assert blobs["pause_blob_node"]["tool_call_records"] == [{"tool_name": "x"}]
