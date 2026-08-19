"""
WebSocket endpoint for agent chat.

Accepts connections, routes client messages, and spawns turn handlers.
Turn orchestration lives in ``src.api.chat``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.chat import handle_chat_request, handle_chat_resume
from src.api.deps import get_current_user
from src.api.websocket_connection import WebSocketConnection
from src.auth import AuthConfigurationError, AuthError
from src.core.logger import get_logger
from src.core.websocket_traffic_logger import log_websocket_traffic
from src.db import ConversationService, User, get_db
from src.schemas.websocket import (
    ChatRequestMessage,
    ChatResumeMessage,
    ClientMessageType,
)

logger = get_logger("websocket")
router = APIRouter()


async def _cancel_active_task(task: asyncio.Task[None] | None) -> None:
    """Cancel and drain an in-flight WebSocket handler task."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Active WebSocket request task failed during cancellation")


async def _keepalive_during_task(
    conn: WebSocketConnection,
    task: asyncio.Task[None],
    *,
    interval_seconds: float = 25.0,
) -> None:
    """Send lightweight status updates while a long-running handler is active."""
    from src.schemas.websocket import AgentStage

    while not task.done() and not conn.is_closed:
        await asyncio.sleep(interval_seconds)
        if task.done() or conn.is_closed:
            return
        await conn.send_status(AgentStage.PLANNING, "Still working...")


def _spawn_request_task(
    conn: WebSocketConnection,
    coro: Any,
) -> tuple[asyncio.Task[None], asyncio.Task[None]]:
    """Start a request handler and a keepalive companion task."""
    request_task = asyncio.create_task(coro)
    keepalive_task = asyncio.create_task(_keepalive_during_task(conn, request_task))

    def _stop_keepalive(_done: asyncio.Task[None]) -> None:
        if not keepalive_task.done():
            keepalive_task.cancel()

    request_task.add_done_callback(_stop_keepalive)
    return request_task, keepalive_task


async def _reject_if_busy(
    conn: WebSocketConnection,
    active_task: asyncio.Task[None] | None,
) -> bool:
    """Return True if a request is already running (and an error was sent)."""
    if active_task and not active_task.done():
        await conn.send_error(
            "A request is already running. Cancel it before starting another.",
            recoverable=True,
        )
        return True
    return False


@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    WebSocket endpoint for real-time chat with the agent.

    1. Accept connection and send acknowledgment
    2. Route client messages to chat handlers
    3. Cancel in-flight work on disconnect / explicit cancel
    """
    conn = WebSocketConnection(websocket, user_id=user.id)
    conversations = ConversationService(db)
    active_task: asyncio.Task[None] | None = None
    keepalive_task: asyncio.Task[None] | None = None

    try:
        await conn.accept()
        log_websocket_traffic(
            event="connection_open",
            direction="server",
            connection_id=conn.connection_id,
            user_id=conn.user_id,
            message_type=None,
            payload={"path": websocket.url.path},
        )
        logger.info("WebSocket connection established")

        while True:
            if active_task and active_task.done():
                try:
                    await active_task
                except asyncio.CancelledError:
                    logger.info("Active WebSocket request task was cancelled")
                except Exception:
                    logger.exception("Active WebSocket request task failed")
                active_task = None
                if keepalive_task and not keepalive_task.done():
                    keepalive_task.cancel()
                keepalive_task = None

            raw_data = ""
            try:
                raw_data = await websocket.receive_text()
                data = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                log_websocket_traffic(
                    event="invalid_json",
                    direction="client_to_server",
                    connection_id=conn.connection_id,
                    user_id=conn.user_id,
                    message_type=None,
                    payload={"raw": raw_data, "error": str(exc)},
                )
                logger.warning("Received invalid JSON from client: %s", exc)
                await conn.send_error(f"Invalid JSON: {exc}", recoverable=True)
                continue

            msg_type = data.get("type") if isinstance(data, dict) else None
            log_websocket_traffic(
                direction="client_to_server",
                connection_id=conn.connection_id,
                user_id=conn.user_id,
                message_type=msg_type,
                payload=data,
            )
            if not isinstance(data, dict):
                logger.warning("Received non-object JSON from client")
                await conn.send_error(
                    "Invalid message format: expected JSON object",
                    recoverable=True,
                )
                continue

            logger.debug("Received message type: %s", msg_type)

            if msg_type == ClientMessageType.CHAT_REQUEST.value:
                try:
                    if await _reject_if_busy(conn, active_task):
                        continue
                    request = ChatRequestMessage.model_validate(data)
                    conn.reset_cancellation()
                    active_task, keepalive_task = _spawn_request_task(
                        conn,
                        handle_chat_request(
                            conn,
                            request.to_message(),
                            user,
                            conversations,
                            conversation_id=request.conversation_id,
                            language=request.language,
                        ),
                    )
                except ValidationError as exc:
                    logger.error("Chat request validation error: %s", exc)
                    await conn.send_error(
                        f"Invalid message format: {exc}", recoverable=True
                    )

            elif msg_type == ClientMessageType.CHAT_RESUME.value:
                try:
                    if await _reject_if_busy(conn, active_task):
                        continue
                    request = ChatResumeMessage.model_validate(data)
                    conn.reset_cancellation()
                    active_task, keepalive_task = _spawn_request_task(
                        conn,
                        handle_chat_resume(
                            conn,
                            request.to_message(),
                            user,
                            conversations,
                            conversation_id=request.conversation_id,
                        ),
                    )
                except ValidationError as exc:
                    logger.error("Chat resume validation error: %s", exc)
                    await conn.send_error(
                        f"Invalid message format: {exc}", recoverable=True
                    )

            elif msg_type == ClientMessageType.CANCEL.value:
                # Soft-cancel the handler (checks is_cancelled after graph) and
                # hard-cancel the asyncio task so keepalive / wait stops.
                conn.cancel()
                logger.info("Client requested cancellation")
                await _cancel_active_task(active_task)
                active_task = None
                if keepalive_task and not keepalive_task.done():
                    keepalive_task.cancel()
                keepalive_task = None
                await conn.send_complete(response="Request cancelled.", error=False)

            else:
                logger.warning("Unknown message type received: %s", msg_type)
                await conn.send_error(
                    f"Unknown message type: {msg_type}", recoverable=True
                )

    except AuthError as exc:
        logger.warning("WebSocket authentication failed: %s", exc.message)
    except AuthConfigurationError:
        logger.exception("WebSocket authentication is misconfigured")
    except WebSocketDisconnect as exc:
        conn.mark_closed()
        await _cancel_active_task(active_task)
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
        log_websocket_traffic(
            event="connection_closed",
            direction="client",
            connection_id=conn.connection_id,
            user_id=conn.user_id,
            message_type=None,
            payload={"code": exc.code, "reason": exc.reason},
        )
        logger.info("WebSocket disconnected")
    except Exception:
        conn.mark_closed()
        await _cancel_active_task(active_task)
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
        logger.exception("WebSocket error")
        try:
            await conn.send_error("Internal server error", recoverable=False)
        except Exception:
            pass
