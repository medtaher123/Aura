"""Configuration protocol for Bedrock LLM adapters."""

from __future__ import annotations

from typing import Protocol


class BedrockLLMSettings(Protocol):
    """Bedrock LLM settings consumed by the graph adapter."""

    bedrock_llm_enabled: bool
    bedrock_region: str
    bedrock_endpoint: str
    bedrock_router_model_id: str
    bedrock_tool_planner_model_id: str
