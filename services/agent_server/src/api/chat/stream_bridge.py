"""Keep a WebSocket stream subscriber alive for one graph turn."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from src.api.websocket_connection import WebSocketConnection
from src.api.websocket_stream_subscriber import WebSocketStreamSubscriber
from src.core.event_emitter import EventEmitter


@contextmanager
def stream_bridge(conn: WebSocketConnection) -> Iterator[EventEmitter]:
    """Yield a request-scoped emitter whose WS subscriber stays strongly referenced.

    EventEmitter stores weak refs to subscriber methods; without holding the
    subscriber object, handlers disappear mid-turn and streaming stops.
    """
    loop = asyncio.get_running_loop()
    emitter = EventEmitter()
    subscriber = WebSocketStreamSubscriber(conn, loop, emitter=emitter)
    try:
        yield emitter
    finally:
        # Explicitly keep ``subscriber`` alive until the graph turn finishes.
        del subscriber
