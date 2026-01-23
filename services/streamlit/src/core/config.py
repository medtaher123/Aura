"""
Configuration module for Metaplanet LLM
Contains environment and application settings
"""

import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Data directory
DATA_DIR = PROJECT_ROOT / "Data"

# Model settings
DEFAULT_LLM_MODEL = "mistral"
DEFAULT_LLM_TEMPERATURE = 0.1

# STAC settings
STAC_API_URL = "https://earth-search.aws.element84.com/v1"
STAC_REQUEST_TIMEOUT = 10

# API keys (from environment variables)
MAP_KEY = os.getenv("MAP_KEY", "f44596f0cc01c26985abd6bfff78ac92")
OPENTOP_API_KEY = os.getenv("OPENTOPO_API_KEY", "811d1f7cbb4522dc7e623ec70a657ed1")

# Archive directory
ARCHIVE_DIR = DATA_DIR if DATA_DIR.exists() else "./Data"
