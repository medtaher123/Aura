"""
Core module - Contains configuration, logging, prompts and initialization utilities
"""

from .prompts import get_prompt_config
from .config import PROJECT_ROOT, DATA_DIR, ARCHIVE_DIR
from .logger import get_logger

__all__ = [
    "get_prompt_config",
    "PROJECT_ROOT",
    "DATA_DIR",
    "ARCHIVE_DIR",
    "get_logger",
]
