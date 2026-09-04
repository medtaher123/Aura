"""Tests for GraphNode lifecycle start/end event emission."""

from __future__ import annotations

from typing import Any

import pytest

from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, GraphStateModel
from src.core.event_emitter import (
    EventEmitter,
    GraphNodeLifecycleEvent,
    reset_stream_emitter,
    set_stream_emitter,
)


class _ProbeNode(GraphNode):
    node_name = "probe"
    status_message = "Probing..."
    emit_node_lifecycle = True

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self._payload = payload or {"ok": True}

    async def run(self, s: GraphStateModel) -> GraphState:
        return dict(self._payload)


class _SilentNode(_ProbeNode):
    node_name = "silent"
    emit_node_lifecycle = False


@pytest.mark.asyncio
async def test_graph_node_emits_start_and_end_with_result() -> None:
    events: list[Any] = []
    emitter = EventEmitter()
    emitter.add_listener(GraphNodeLifecycleEvent, events.append)
    token = set_stream_emitter(emitter)
    try:
        out = await _ProbeNode({"answer": 42})({})
    finally:
        reset_stream_emitter(token)

    assert out == {"answer": 42}
    assert len(events) == 2
    assert events[0].phase == "running"
    assert events[0].node_name == "probe"
    assert events[0].message == "Probing..."
    assert events[0].result is None
    assert events[1].phase == "done"
    assert events[1].result == {"answer": 42}
    assert events[1].error is False


@pytest.mark.asyncio
async def test_graph_node_can_disable_lifecycle_events() -> None:
    events: list[Any] = []
    emitter = EventEmitter()
    emitter.add_listener(GraphNodeLifecycleEvent, events.append)
    token = set_stream_emitter(emitter)
    try:
        await _SilentNode({"x": 1})({})
    finally:
        reset_stream_emitter(token)

    assert events == []
