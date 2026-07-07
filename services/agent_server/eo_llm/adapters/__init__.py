"""External adapters (MCP, Bedrock LLM, web search)."""

from eo_llm.adapters.bedrock import BedrockLLMAdapter, create_bedrock_llm_adapter

__all__ = ["BedrockLLMAdapter", "create_bedrock_llm_adapter"]
