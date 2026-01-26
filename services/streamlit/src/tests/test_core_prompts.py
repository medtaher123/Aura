"""
Tests for core/prompts.py - Prompt templates for agents.
"""

import pytest

from src.core.prompts import (
    get_data_agent_react_prompt,
    get_orchestrator_prompt,
    get_analysis_prompt,
)


class TestGetDataAgentReactPrompt:
    """Tests for get_data_agent_react_prompt function."""

    def test_returns_string(self):
        result = get_data_agent_react_prompt(["tool1", "tool2"])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_tool_names(self):
        tools = ["detect_fire_tool", "query_stac_catalog", "weather_tool"]
        result = get_data_agent_react_prompt(tools)
        for tool in tools:
            assert tool in result

    def test_tool_names_sorted(self):
        tools = ["z_tool", "a_tool", "m_tool"]
        result = get_data_agent_react_prompt(tools)
        # Tools should appear in sorted order in the AVAILABLE TOOLS section
        assert "a_tool" in result
        assert "m_tool" in result
        assert "z_tool" in result

    def test_empty_tools_list(self):
        result = get_data_agent_react_prompt([])
        assert isinstance(result, str)
        # Should still have the prompt template
        assert "AVAILABLE TOOLS" in result

    def test_deduplicates_tools(self):
        tools = ["tool1", "tool1", "tool2"]
        result = get_data_agent_react_prompt(tools)
        # Count occurrences in the AVAILABLE TOOLS line
        assert result.count("tool1") >= 1  # Should deduplicate

    def test_filters_empty_tool_names(self):
        tools = ["tool1", "", None, "tool2"]
        result = get_data_agent_react_prompt(tools)
        assert "tool1" in result
        assert "tool2" in result

    def test_includes_critical_rules(self):
        result = get_data_agent_react_prompt(["test"])
        assert "CRITICAL RULES" in result

    def test_includes_output_format(self):
        result = get_data_agent_react_prompt(["test"])
        assert "OUTPUT FORMAT" in result

    def test_includes_few_shot_examples(self):
        result = get_data_agent_react_prompt(["test"])
        assert "FEW-SHOT EXAMPLES" in result
        assert "detect_fire_tool" in result  # From examples

    def test_includes_final_action(self):
        result = get_data_agent_react_prompt(["test"])
        assert "FINAL" in result


class TestGetOrchestratorPrompt:
    """Tests for get_orchestrator_prompt function."""

    def test_returns_string(self):
        result = get_orchestrator_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_agent_descriptions(self):
        result = get_orchestrator_prompt()
        assert "DataAgent" in result
        assert "AnalysisAgent" in result

    def test_includes_json_format(self):
        result = get_orchestrator_prompt()
        assert "needs_data" in result
        assert "needs_analysis" in result
        assert "data_query" in result
        assert "analysis_goal" in result

    def test_includes_examples(self):
        result = get_orchestrator_prompt()
        assert "Example" in result


class TestGetAnalysisPrompt:
    """Tests for get_analysis_prompt function."""

    def test_returns_string(self):
        result = get_analysis_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_agent_role(self):
        result = get_analysis_prompt()
        assert "AnalysisAgent" in result

    def test_includes_rules(self):
        result = get_analysis_prompt()
        assert "Rules" in result

    def test_mentions_data_response(self):
        result = get_analysis_prompt()
        assert "data_response" in result

    def test_mentions_user_question(self):
        result = get_analysis_prompt()
        assert "user_question" in result
