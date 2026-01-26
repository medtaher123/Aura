"""
Tests for services/agent_runner.py - Agent invocation wrapper.
"""

import pytest
from unittest.mock import MagicMock

from src.services.agent_runner import invoke_agent, coerce_tool_response
from src.tools.contracts import make_tool_response


class TestInvokeAgent:
    """Tests for invoke_agent function."""

    def test_basic_invocation(self):
        """Test basic agent invocation."""
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = {"output": "result"}

        result = invoke_agent(mock_executor, "test query")

        mock_executor.invoke.assert_called_once()
        call_args = mock_executor.invoke.call_args[0][0]
        assert call_args["input"] == "test query"
        assert result == "result"

    def test_with_chat_history(self):
        """Test invocation with chat history."""
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = {"output": "result"}
        history = [{"role": "user", "content": "previous"}]

        invoke_agent(mock_executor, "query", chat_history=history)

        call_args = mock_executor.invoke.call_args[0][0]
        assert call_args["chat_history"] == history

    def test_with_resume(self):
        """Test invocation with resume state."""
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = {"output": "result"}
        resume_state = {"step": 2, "data": "saved"}

        invoke_agent(mock_executor, "query", resume=resume_state)

        call_args = mock_executor.invoke.call_args[0][0]
        assert call_args["resume"] == resume_state

    def test_with_stream_callback(self):
        """Test invocation with stream callback."""
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = {"output": "result"}
        callback = MagicMock()

        invoke_agent(mock_executor, "query", stream_callback=callback)

        call_args = mock_executor.invoke.call_args[0][0]
        assert call_args["stream_callback"] == callback

    def test_returns_output_when_dict(self):
        """Test that output is extracted from dict response."""
        mock_executor = MagicMock()
        expected_output = {"message": "done", "data": {}}
        mock_executor.invoke.return_value = {"output": expected_output, "other": "stuff"}

        result = invoke_agent(mock_executor, "query")

        assert result == expected_output

    def test_returns_full_dict_when_no_output(self):
        """Test that full dict is returned when no output key."""
        mock_executor = MagicMock()
        response = {"some": "data", "other": "stuff"}
        mock_executor.invoke.return_value = response

        result = invoke_agent(mock_executor, "query")

        assert result == response

    def test_returns_non_dict_as_is(self):
        """Test that non-dict responses are returned as-is."""
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = "string result"

        result = invoke_agent(mock_executor, "query")

        assert result == "string result"


class TestCoerceToolResponse:
    """Tests for coerce_tool_response function."""

    def test_valid_tool_response_passed_through(self):
        """Test that valid ToolResponse is passed through with artifact normalization."""
        response = make_tool_response(
            tool_name="test_tool",
            message="Test message",
            artifacts={"maps": ["map1"], "thumbnails": [], "urls": []},
            error=False,
        )

        result = coerce_tool_response(response)

        assert result["tool_name"] == "test_tool"
        assert result["message"] == "Test message"
        assert result["error"] is False

    def test_normalizes_missing_artifact_keys(self):
        """Test that missing artifact keys are added."""
        response = {
            "tool_name": "test",
            "message": "msg",
            "artifacts": {"maps": []},  # Missing thumbnails and urls
            "error": False,
        }

        result = coerce_tool_response(response)

        assert "thumbnails" in result["artifacts"]
        assert "urls" in result["artifacts"]

    def test_handles_none_artifacts(self):
        """Test handling of None artifacts."""
        response = {
            "tool_name": "test",
            "message": "msg",
            "artifacts": None,
            "error": False,
        }

        result = coerce_tool_response(response)

        assert result["artifacts"]["maps"] == []
        assert result["artifacts"]["thumbnails"] == []
        assert result["artifacts"]["urls"] == []

    def test_legacy_dict_without_required_keys(self):
        """Test handling of legacy dict without required ToolResponse keys."""
        response = {"result": "some data", "status": "ok"}

        result = coerce_tool_response(response)

        assert result["tool_name"] == "unknown"
        assert isinstance(result["message"], str)
        assert result["error"] is False

    def test_dict_with_message_but_incomplete(self):
        """Test dict that has message but is incomplete."""
        response = {"message": "partial result"}

        result = coerce_tool_response(response)

        assert result["tool_name"] == "unknown"
        assert result["message"] == "partial result"

    def test_string_input(self):
        """Test handling of string input."""
        result = coerce_tool_response("Just a string result")

        assert result["tool_name"] == "unknown"
        assert result["message"] == "Just a string result"
        assert result["error"] is False

    def test_numeric_input(self):
        """Test handling of numeric input."""
        result = coerce_tool_response(42)

        assert result["tool_name"] == "unknown"
        assert result["message"] == "42"

    def test_none_input(self):
        """Test handling of None input."""
        result = coerce_tool_response(None)

        assert result["tool_name"] == "unknown"
        assert isinstance(result["message"], str)

    def test_list_input(self):
        """Test handling of list input."""
        result = coerce_tool_response([1, 2, 3])

        assert result["tool_name"] == "unknown"
        assert isinstance(result["message"], str)

    def test_preserves_all_required_keys(self):
        """Test that result has all required ToolResponse keys."""
        result = coerce_tool_response("test")

        required_keys = [
            "message", "artifacts", "tool_name", "start_date", 
            "end_date", "country", "city", "coordinates", "data", "error"
        ]
        for key in required_keys:
            assert key in result
