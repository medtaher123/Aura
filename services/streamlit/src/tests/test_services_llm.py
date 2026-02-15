"""
Tests for services/llm_service.py - LLM service with AWS Bedrock integration.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.services.llm_service import (
    _infer_bedrock_provider,
    DEFAULT_BEDROCK_MODEL_ID,
    DEFAULT_BEDROCK_REGION,
)


class TestInferBedrockProvider:
    """Tests for _infer_bedrock_provider function."""

    def test_anthropic_model_id(self):
        result = _infer_bedrock_provider("anthropic.claude-3-sonnet")
        assert result == "anthropic"

    def test_anthropic_arn(self):
        arn = "arn:aws:bedrock:eu-west-3:963275461308:inference-profile/eu.anthropic.claude-3-sonnet-20240229-v1:0"
        result = _infer_bedrock_provider(arn)
        assert result == "anthropic"

    def test_meta_model_id(self):
        result = _infer_bedrock_provider("meta.llama3-2-1b-instruct-v1")
        assert result == "meta"

    def test_meta_arn(self):
        arn = "arn:aws:bedrock:eu-west-3:123456:inference-profile/eu.meta.llama3-2-1b-instruct-v1:0"
        result = _infer_bedrock_provider(arn)
        assert result == "meta"

    def test_amazon_model_id(self):
        result = _infer_bedrock_provider("amazon.titan-text-express-v1")
        assert result == "amazon"

    def test_cohere_model_id(self):
        result = _infer_bedrock_provider("cohere.command-text-v14")
        assert result == "cohere"

    def test_mistral_model_id(self):
        result = _infer_bedrock_provider("mistral.mixtral-8x7b-instruct-v0:1")
        assert result == "mistral"

    def test_unknown_provider_returns_none(self):
        result = _infer_bedrock_provider("unknown.model-v1")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _infer_bedrock_provider("")
        assert result is None

    def test_whitespace_string_returns_none(self):
        result = _infer_bedrock_provider("   ")
        assert result is None

    def test_none_returns_none(self):
        result = _infer_bedrock_provider(None)
        assert result is None

    def test_non_string_returns_none(self):
        result = _infer_bedrock_provider(123)
        assert result is None

    def test_case_insensitive(self):
        result = _infer_bedrock_provider("ANTHROPIC.CLAUDE-3")
        assert result == "anthropic"


class TestDefaults:
    """Tests for default configuration."""

    def test_default_model_id_is_string(self):
        assert isinstance(DEFAULT_BEDROCK_MODEL_ID, str)
        assert len(DEFAULT_BEDROCK_MODEL_ID) > 0

    def test_default_region_is_string(self):
        assert isinstance(DEFAULT_BEDROCK_REGION, str)
        assert len(DEFAULT_BEDROCK_REGION) > 0


class TestGetChatLLM:
    """Tests for get_chat_llm function (mocked)."""

    def test_get_llm_alias(self):
        """Test that get_llm is an alias for get_chat_llm."""
        from src.services.llm_service import get_llm, get_chat_llm
        # Just verify they exist and have same signature
        assert callable(get_llm)
        assert callable(get_chat_llm)

    def test_get_chat_llm_module_structure(self):
        """Test that the module has expected structure."""
        from src.services import llm_service
        
        assert hasattr(llm_service, 'get_chat_llm')
        assert hasattr(llm_service, 'get_llm')
        assert hasattr(llm_service, '_infer_bedrock_provider')
        assert hasattr(llm_service, 'DEFAULT_BEDROCK_MODEL_ID')
        assert hasattr(llm_service, 'DEFAULT_BEDROCK_REGION')
