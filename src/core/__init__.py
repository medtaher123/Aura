"""
Core module - Contains configuration, logging, prompts and initialization utilities
"""

from .config import PROJECT_ROOT, DATA_DIR, ARCHIVE_DIR
from .logger import get_logger

__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "ARCHIVE_DIR",
    "get_logger",
]
