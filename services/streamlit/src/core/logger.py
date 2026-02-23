"""
Logger module for Metaplanet LLM
Centralizes logging configuration with enhanced features
"""

import logging
import sys
import os
from pathlib import Path

# Log level from environment or default to INFO
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Enable file logging if LOG_FILE is set
LOG_FILE = os.getenv("LOG_FILE")

# Create logger
logger = logging.getLogger("metaplanet")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Prevent duplicate handlers
logger.handlers.clear()

# Create formatters
detailed_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

simple_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
console_handler.setFormatter(simple_formatter)
logger.addHandler(console_handler)

# File handler (if LOG_FILE is set)
if LOG_FILE:
    try:
        log_path = Path(LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.DEBUG)  # Capture all levels in file
        file_handler.setFormatter(detailed_formatter)
        logger.addHandler(file_handler)
        logger.info(f"File logging enabled: {LOG_FILE}")
    except Exception as e:
        logger.warning(f"Failed to setup file logging: {e}")


def get_logger(name: str = "metaplanet") -> logging.Logger:
    """
    Get or create a logger instance.

    Args:
        name: Logger name (defaults to 'metaplanet')

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def log_function_call(func_name: str, **kwargs) -> None:
    """
    Log a function call with its parameters.

    Args:
        func_name: Name of the function being called
        **kwargs: Function parameters to log
    """
    logger.debug(f"Calling {func_name} with params: {kwargs}")


def log_error_with_context(error: Exception, context: str = "") -> None:
    """
    Log an error with additional context.

    Args:
        error: The exception that occurred
        context: Additional context about where/why the error occurred
    """
    if context:
        logger.error(f"{context}: {type(error).__name__}: {str(error)}", exc_info=True)
    else:
        logger.error(f"{type(error).__name__}: {str(error)}", exc_info=True)


def set_log_level(level: str) -> None:
    """
    Dynamically change log level.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            handler.setLevel(numeric_level)
    logger.info(f"Log level changed to {level.upper()}")
