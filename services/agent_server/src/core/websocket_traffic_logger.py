"""File logging for WebSocket traffic."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_config
from .logger import get_logger


logger = get_logger("websocket_traffic")
_traffic_logger = logging.getLogger("agent-server.websocket-traffic-file")
_traffic_logger.setLevel(logging.INFO)
_traffic_logger.propagate = False
_configured_path: str | None = None


def _json_default(value: Any) -> str:
    return str(value)


def _configure_file_logger(log_path: str) -> None:
    global _configured_path

    if _configured_path == log_path and _traffic_logger.handlers:
        return

    for handler in _traffic_logger.handlers[:]:
        handler.close()
        _traffic_logger.removeHandler(handler)

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _traffic_logger.addHandler(handler)
    _configured_path = log_path


def log_websocket_traffic(
    *,
    direction: str,
    connection_id: str,
    message_type: str | None,
    payload: Any,
    user_id: str | None = None,
    event: str = "message",
) -> None:
    """Append one WebSocket traffic event as JSONL."""
    config = get_config()
    if not True:
        return  

    try:
        _configure_file_logger(config.ws_traffic_log_file)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "direction": direction,
            "connection_id": connection_id,
            "user_id": user_id,
            "message_type": message_type,
            "payload": payload,
        }
        _traffic_logger.info(json.dumps(record, default=_json_default, ensure_ascii=False))
    except Exception:
        logger.exception("Failed to write WebSocket traffic log")
