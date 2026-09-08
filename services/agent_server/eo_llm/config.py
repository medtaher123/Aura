"""Config shim for the ported EO_LLM graph/adapters.

The graph and adapters import `eo_llm.config.get_config()` to read Bedrock LLM
settings. To keep a single source of truth, we re-export the agent server's
configuration. `get_config` remains an lru_cache, so
`eo_llm.config.get_config.cache_clear()` keeps working for tests that toggle
environment variables.
"""

from __future__ import annotations

from src.config import AgentServerConfig as EOConfig
from src.config import get_config

__all__ = ["EOConfig", "get_config"]
