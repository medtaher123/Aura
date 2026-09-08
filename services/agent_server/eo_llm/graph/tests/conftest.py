"""Shared fixtures for eo_llm graph tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from eo_llm.graph.hitl import state_update_from_attachments
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphStateModel, dump_state


async def simulate_hitl_resume(
    node: GraphNode,
    s: GraphStateModel,
    attachments: list[dict[str, Any]],
    *,
    blob: dict[str, Any] | None = None,
) -> GraphStateModel:
    """Apply resume attachments + node blob the way production resume does."""
    payload_blob = blob or {}
    patch = state_update_from_attachments(
        attachments,
        {node.node_name: payload_blob},
    )
    merged = {**dump_state(s), **patch}
    return node.apply_hitl_blob(GraphStateModel.model_validate(merged), payload_blob)


@pytest.fixture(scope="session", autouse=True)
def _init_graph_checkpointer():
    from src.services.graph_runner.checkpointer import init_checkpointer, shutdown_checkpointer

    asyncio.run(init_checkpointer())
    yield
    asyncio.run(shutdown_checkpointer())
