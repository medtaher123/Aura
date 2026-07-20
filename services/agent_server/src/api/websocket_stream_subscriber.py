"""Forward typed stream events from a request-scoped EventEmitter to a WebSocket."""

from __future__ import annotations

import asyncio
from typing import Any

from eo_llm.stream.decision_reasoning import thinking_payload_from_event
from src.api.websocket_connection import WebSocketConnection
from src.core.event_emitter import (
    DataAgentStepEvent,
    EventEmitter,
    EventSubscriber,
    GraphStatusEvent,
    GraphStatusStage,
    ThinkingStreamEvent,
    TokenStreamEvent,
    on_event,
)
from src.core.logger import get_logger
from src.schemas.websocket import AgentStage

logger = get_logger("websocket_stream_subscriber")

_STAGE_TO_AGENT: dict[str, AgentStage] = {
    "planning": AgentStage.PLANNING,
    "tool_call": AgentStage.TOOL_CALL,
    "analyzing": AgentStage.ANALYZING,
}


class WebSocketStreamSubscriber(EventSubscriber):
    """Listens for stream events and sends matching websocket messages."""

    def __init__(
        self,
        conn: WebSocketConnection,
        event_loop: asyncio.AbstractEventLoop,
        *,
        emitter: EventEmitter,
    ) -> None:
        self.emitter = emitter
        self._conn = conn
        self._event_loop = event_loop

    def _schedule(self, coro: Any) -> None:
        try:
            asyncio.run_coroutine_threadsafe(coro, self._event_loop)
        except Exception as exc:
            logger.warning(f"Stream websocket schedule error: {exc}")

    @staticmethod
    def _agent_stage(stage: GraphStatusStage | str) -> AgentStage:
        return _STAGE_TO_AGENT.get(stage, AgentStage.PLANNING)

    @on_event(TokenStreamEvent)
    def on_token(self, event: TokenStreamEvent) -> None:
        if event.content:
            self._schedule(self._conn.send_token(event.content))

    @on_event(ThinkingStreamEvent)
    def on_thinking(self, event: ThinkingStreamEvent) -> None:
        payload = thinking_payload_from_event(event)
        if payload is None:
            return
        self._schedule(
            self._conn.send_thinking(
                source=payload["source"],
                content=payload["content"],
                reasoning=payload["reasoning"],
                stage=self._agent_stage(payload["stage"]),
            )
        )

    @on_event(GraphStatusEvent)
    def on_graph_status(self, event: GraphStatusEvent) -> None:
        self._schedule(
            self._conn.send_status(self._agent_stage(event.stage), event.message)
        )

    @on_event(DataAgentStepEvent)
    def on_data_agent_step(self, event: DataAgentStepEvent) -> None:
        self._schedule(self._forward_tool_step(event))

    async def _forward_tool_step(self, event: DataAgentStepEvent) -> None:
        if event.phase == "running":
            await self._conn.send_tool_start(
                event.tool_name,
                event.tool_input,
                step_id=event.step_id,
                domain=event.domain,
            )
            return

        if event.phase != "done":
            return

        await self._conn.send_tool_result(
            tool_name=event.tool_name,
            result={
                "observation": event.observation,
                "error": event.error,
                "status": event.status,
                "attempts": event.attempts,
                "step_id": event.step_id,
                "domain": event.domain,
                "execution_time_seconds": event.execution_time_seconds,
            },
            artifacts=event.artifacts,
            step_id=event.step_id,
            domain=event.domain,
            execution_time_seconds=event.execution_time_seconds,
        )
