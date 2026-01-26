"""
Tests for services/analysis_agent_service.py - Analysis agent executor.
"""

import pytest
from unittest.mock import MagicMock

from src.services.analysis_agent_service import AnalysisAgentExecutor
from src.tools.contracts import make_tool_response


class _MockMessage:
    """Mock LLM response message."""
    def __init__(self, content: str):
        self.content = content


class TestAnalysisAgentExecutor:
    """Tests for AnalysisAgentExecutor class."""

    def test_basic_invocation(self):
        """Test basic analysis invocation."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Analysis complete: Fire detected.")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        data_response = make_tool_response(
            tool_name="detect_fire_tool",
            message="5 fires detected",
            artifacts={"maps": ["fire_map"], "thumbnails": [], "urls": []},
            error=False,
        )

        result = executor.invoke({
            "user_question": "Are there fires in Berlin?",
            "data_response": data_response,
        })

        assert "output" in result
        output = result["output"]
        assert output["tool_name"] == "analysis_agent"
        assert "Analysis complete" in output["message"]
        assert output["error"] is False

    def test_preserves_artifacts_from_data_response(self):
        """Test that artifacts from DataAgent are preserved."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Analysis done")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        artifacts = {"maps": ["map1", "map2"], "thumbnails": ["thumb1"], "urls": ["url1"]}
        data_response = make_tool_response(
            tool_name="test_tool",
            message="test",
            artifacts=artifacts,
            error=False,
        )

        result = executor.invoke({
            "user_question": "Analyze",
            "data_response": data_response,
        })

        output = result["output"]
        assert output["artifacts"] == artifacts

    def test_preserves_metadata_from_data_response(self):
        """Test that metadata (dates, location) is preserved."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Analysis done")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        data_response = make_tool_response(
            tool_name="test_tool",
            message="test",
            start_date="2024-01-01",
            end_date="2024-12-31",
            country="France",
            city="Paris",
            coordinates={"lat": 48.8566, "lon": 2.3522},
            error=False,
        )

        result = executor.invoke({
            "user_question": "Analyze",
            "data_response": data_response,
        })

        output = result["output"]
        assert output["start_date"] == "2024-01-01"
        assert output["end_date"] == "2024-12-31"
        assert output["country"] == "France"
        assert output["city"] == "Paris"
        assert output["coordinates"]["lat"] == 48.8566

    def test_includes_source_tool_in_data(self):
        """Test that source tool is recorded in data."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Done")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        data_response = make_tool_response(
            tool_name="original_tool",
            message="test",
            error=False,
        )

        result = executor.invoke({
            "user_question": "Analyze",
            "data_response": data_response,
        })

        output = result["output"]
        assert output["data"]["source_tool"] == "original_tool"

    def test_handles_empty_data_response(self):
        """Test handling of empty/None data response."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Cannot analyze without data")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        result = executor.invoke({
            "user_question": "Analyze",
            "data_response": None,
        })

        output = result["output"]
        assert output["tool_name"] == "analysis_agent"
        assert output["error"] is False

    def test_handles_non_dict_data_response(self):
        """Test handling of non-dict data response."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Got string response")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        result = executor.invoke({
            "user_question": "Analyze",
            "data_response": "Just a string",
        })

        output = result["output"]
        assert output["tool_name"] == "analysis_agent"

    def test_includes_context_in_prompt(self):
        """Test that conversation context is included in prompt."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Analysis with context")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        result = executor.invoke({
            "user_question": "Continue analysis",
            "data_response": {},
            "context": "Previous: discussed fires in Berlin",
        })

        # Check that LLM was called with context
        call_args = mock_llm.invoke.call_args[0][0]
        human_message = call_args[-1]
        assert "Previous: discussed fires in Berlin" in human_message.content

    def test_empty_context_not_included(self):
        """Test that empty context is not included."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Done")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        result = executor.invoke({
            "user_question": "Analyze",
            "data_response": {},
            "context": "",
        })

        call_args = mock_llm.invoke.call_args[0][0]
        human_message = call_args[-1]
        assert "conversation_context" not in human_message.content

    def test_llm_receives_system_and_human_messages(self):
        """Test that LLM receives proper message structure."""
        from langchain_core.messages import SystemMessage, HumanMessage

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _MockMessage("Done")

        executor = AnalysisAgentExecutor(llm=mock_llm)

        executor.invoke({
            "user_question": "Test",
            "data_response": {},
        })

        call_args = mock_llm.invoke.call_args[0][0]
        assert len(call_args) == 2
        assert isinstance(call_args[0], SystemMessage)
        assert isinstance(call_args[1], HumanMessage)
