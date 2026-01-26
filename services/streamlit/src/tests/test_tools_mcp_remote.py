"""
Tests for tools/mcp_remote_tools.py - MCP server tool adapter.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json

from src.tools.mcp_remote_tools import (
    _mcp_sse_url,
    _coerce_args,
    _parse_mcp_call_result,
    MCPRemoteTool,
)


class TestMcpSseUrl:
    """Tests for _mcp_sse_url function."""

    def test_default_url(self):
        with patch.dict("os.environ", {}, clear=True):
            # Remove MCP_SERVER_URL if it exists
            with patch.dict("os.environ", {"MCP_SERVER_URL": ""}, clear=False):
                url = _mcp_sse_url()
                assert url == "http://localhost:8000/sse"

    def test_custom_url_without_sse(self):
        with patch.dict("os.environ", {"MCP_SERVER_URL": "http://custom:9000"}):
            url = _mcp_sse_url()
            assert url == "http://custom:9000/sse"

    def test_custom_url_with_sse(self):
        with patch.dict("os.environ", {"MCP_SERVER_URL": "http://custom:9000/sse"}):
            url = _mcp_sse_url()
            assert url == "http://custom:9000/sse"

    def test_strips_trailing_slash(self):
        with patch.dict("os.environ", {"MCP_SERVER_URL": "http://custom:9000/"}):
            url = _mcp_sse_url()
            assert url == "http://custom:9000/sse"


class TestCoerceArgs:
    """Tests for _coerce_args function."""

    def test_dict_input_passed_through(self):
        tool_input = {"key": "value", "num": 42}
        result = _coerce_args(tool_input, None)
        assert result == tool_input

    def test_none_input_returns_empty_dict(self):
        result = _coerce_args(None, None)
        assert result == {}

    def test_single_required_key(self):
        schema = {
            "required": ["query"],
            "properties": {"query": {"type": "string"}}
        }
        result = _coerce_args("test value", schema)
        assert result == {"query": "test value"}

    def test_single_property(self):
        schema = {
            "properties": {"input": {"type": "string"}}
        }
        result = _coerce_args("test value", schema)
        assert result == {"input": "test value"}

    def test_fallback_to_input_key(self):
        schema = {
            "required": ["a", "b"],  # Multiple required
            "properties": {"a": {}, "b": {}}  # Multiple properties
        }
        result = _coerce_args("test", schema)
        assert result == {"input": "test"}

    def test_empty_schema(self):
        result = _coerce_args("test", {})
        assert result == {"input": "test"}

    def test_no_schema(self):
        result = _coerce_args("test", None)
        assert result == {"input": "test"}


class TestParseMcpCallResult:
    """Tests for _parse_mcp_call_result function."""

    def test_json_text_content_parsed(self):
        mock_content = MagicMock()
        mock_content.text = json.dumps({"message": "success", "data": {"count": 5}})

        mock_result = MagicMock()
        mock_result.content = [mock_content]

        result = _parse_mcp_call_result("test_tool", mock_result)
        assert result == {"message": "success", "data": {"count": 5}}

    def test_plain_text_content(self):
        mock_content = MagicMock()
        mock_content.text = "Plain text result"

        mock_result = MagicMock()
        mock_result.content = [mock_content]

        result = _parse_mcp_call_result("test_tool", mock_result)
        assert result["tool_name"] == "test_tool"
        assert result["message"] == "Plain text result"
        assert result["error"] is False

    def test_no_content_returns_raw(self):
        mock_result = MagicMock()
        mock_result.content = None

        result = _parse_mcp_call_result("test_tool", mock_result)
        assert result == mock_result

    def test_empty_content_returns_raw(self):
        mock_result = MagicMock()
        mock_result.content = []

        result = _parse_mcp_call_result("test_tool", mock_result)
        assert result == mock_result

    def test_no_text_attribute(self):
        mock_content = MagicMock(spec=[])  # No text attribute

        mock_result = MagicMock()
        mock_result.content = [mock_content]

        result = _parse_mcp_call_result("test_tool", mock_result)
        assert result == mock_result


class TestMCPRemoteTool:
    """Tests for MCPRemoteTool class."""

    def test_initialization(self):
        tool = MCPRemoteTool(
            name="test_tool",
            description="A test tool",
            input_schema={"properties": {"input": {"type": "string"}}}
        )

        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.input_schema is not None

    def test_default_values(self):
        tool = MCPRemoteTool(name="test")
        assert tool.description == ""
        assert tool.input_schema is None

    def test_invoke_calls_async_function(self):
        """Test that invoke properly calls the async MCP functions."""
        tool = MCPRemoteTool(
            name="test_tool",
            input_schema={"properties": {"query": {"type": "string"}}}
        )

        # Mock the async call
        with patch("src.tools.mcp_remote_tools._run_sync") as mock_run_sync, \
             patch("src.tools.mcp_remote_tools._parse_mcp_call_result") as mock_parse:

            mock_result = MagicMock()
            mock_run_sync.return_value = mock_result
            mock_parse.return_value = {"message": "success"}

            result = tool.invoke({"query": "test"})

            mock_run_sync.assert_called_once()
            mock_parse.assert_called_once_with("test_tool", mock_result)
            assert result == {"message": "success"}

    def test_invoke_coerces_args(self):
        """Test that invoke properly coerces arguments."""
        tool = MCPRemoteTool(
            name="test_tool",
            input_schema={
                "required": ["query"],
                "properties": {"query": {"type": "string"}}
            }
        )

        with patch("src.tools.mcp_remote_tools._run_sync") as mock_run_sync, \
             patch("src.tools.mcp_remote_tools._call_tool_async") as mock_call:

            mock_run_sync.return_value = MagicMock(content=None)

            # Pass a string that should be coerced
            tool.invoke("test string")

            # Check that _call_tool_async was called with coerced args
            call_args = mock_run_sync.call_args[0][0]
            # The coroutine should have been created with {"query": "test string"}


class TestMCPRemoteToolIntegration:
    """Integration-style tests for MCPRemoteTool (mocked MCP server)."""

    def test_langchain_tool_interface(self):
        """Verify tool has expected LangChain-like interface."""
        tool = MCPRemoteTool(name="test_tool", description="Test")

        assert hasattr(tool, "name")
        assert hasattr(tool, "invoke")
        assert callable(tool.invoke)
