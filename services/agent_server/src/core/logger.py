"""
Logger module for Agent Server
Centralizes logging configuration
"""

import logging
import sys
from typing import Optional

LOG_LEVEL = "INFO"

_root_logger = logging.getLogger("agent-server")
_root_logger.setLevel(logging.DEBUG)

_root_logger.handlers.clear()

_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.DEBUG)
_console_handler.setFormatter(_formatter)
_root_logger.addHandler(_console_handler)


def get_logger(name: str = "agent-server") -> logging.Logger:
    """Get or create a logger instance.

    Args:
        name: Logger name (will be prefixed with 'agent-server.' if not the root)

    Returns:
        Logger instance
    """
    if name == "agent-server":
        return _root_logger
    return logging.getLogger(f"agent-server.{name}")


def configure_log_level(level: str) -> None:
    """Configure the log level for all agent-server loggers.

    Args:
        level: Log level string (debug, info, warning, error, critical)
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    _root_logger.setLevel(log_level)
    _console_handler.setLevel(log_level)
