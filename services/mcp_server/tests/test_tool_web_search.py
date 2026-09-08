"""Tests for web_search_tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from modules.utility.web_search import web_search_tool
from utils.contracts import ToolResponse


@pytest.mark.unit
def test_web_search_empty_query() -> None:
    result = web_search_tool(query="  ")
    assert isinstance(result, ToolResponse)
    assert result.error is True
    assert result.data["results"] == []


@pytest.mark.unit
def test_web_search_success() -> None:
    rows = [
        {
            "title": "Flood update",
            "snippet": "River levels rising near Lyon",
            "url": "https://example.com/flood",
        }
    ]
    with patch("modules.utility.web_search._run_search", return_value=("DuckDuckGo", rows)):
        result = web_search_tool(query="floods near Lyon")

    assert result.error is False
    assert result.tool_name == "web_search_tool"
    assert result.data["provider"] == "duckduckgo"
    assert result.data["results"] == rows
    assert "Flood update" in result.message


@pytest.mark.unit
def test_web_search_provider_failure() -> None:
    with patch(
        "modules.utility.web_search._run_search",
        side_effect=RuntimeError("provider down"),
    ):
        result = web_search_tool(query="news")

    assert result.error is True
    assert "provider down" in result.message
    assert result.data["results"] == []


@pytest.mark.unit
def test_web_search_no_usable_rows() -> None:
    with patch(
        "modules.utility.web_search._run_search",
        return_value=("Brave", [{"title": "Empty", "snippet": "", "url": ""}]),
    ):
        result = web_search_tool(query="nothing")

    assert result.error is True
    assert "no results" in result.message.lower()
