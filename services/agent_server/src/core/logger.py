"""
Logger module for Agent Server
Centralizes logging configuration
"""

import logging
import sys
from typing import Optional

# Create root logger for agent server
logger = logging.getLogger("agent-server")
logger.setLevel(logging.DEBUG)

# Create console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
console_handler.setFormatter(formatter)

# Add handler to logger (avoid duplicates)
if not logger.handlers:
    logger.addHandler(console_handler)


def get_logger(name: str = "agent-server") -> logging.Logger:
    """Get or create a logger instance.
    
    Args:
        name: Logger name (will be prefixed with 'agent-server.' if not the root)
        
    Returns:
        Logger instance
    """
    if name == "agent-server":
        return logger
    return logging.getLogger(f"agent-server.{name}")


def configure_log_level(level: str) -> None:
    """Configure the log level for all agent-server loggers.
    
    Args:
        level: Log level string (debug, info, warning, error, critical)
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)
    console_handler.setLevel(log_level)
