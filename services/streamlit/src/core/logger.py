"""
Logger module for Metaplanet LLM
Centralizes logging configuration
"""

import logging
import sys

# Create logger
logger = logging.getLogger("metaplanet")
logger.setLevel(logging.DEBUG)

# Create console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
console_handler.setFormatter(formatter)

# Add handler to logger
if not logger.handlers:
    logger.addHandler(console_handler)

def get_logger(name: str = "metaplanet"):
    """Get or create a logger instance"""
    return logging.getLogger(name)
