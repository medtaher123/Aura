"""
Smoke tests for tools that are local to the streamlit package.

Note: Most tools have been moved to services/mcp_server/tools/ and are
accessed via MCP remote calls. Those tools are tested in
services/mcp_server/tests/. This file only tests the local utility tools.
"""

import pytest


def assert_tool_response(resp: dict, tool_name: str) -> None:
    assert isinstance(resp, dict)

    # Contract keys from src/tools/contracts.py
    expected_keys = {
        "message",
        "artifacts",
        "tool_name",
        "start_date",
        "end_date",
        "country",
        "city",
        "coordinates",
        "data",
        "error",
    }
    assert expected_keys.issubset(resp.keys())

    assert resp["tool_name"] == tool_name
    assert isinstance(resp["message"], str)
    assert resp["message"].strip() != ""

    assert isinstance(resp["error"], bool)

    artifacts = resp["artifacts"]
    assert isinstance(artifacts, dict)
    assert "maps" in artifacts and isinstance(artifacts["maps"], list)
    assert "thumbnails" in artifacts and isinstance(artifacts["thumbnails"], list)
    assert "urls" in artifacts and isinstance(artifacts["urls"], list)


def test_get_date_tool_smoke():
    from src.tools.tools import get_date

    resp = get_date.invoke({})
    assert_tool_response(resp, "get_date")
    assert resp["error"] is False


def test_get_time_tool_smoke():
    from src.tools.tools import get_time

    resp = get_time.invoke({})
    assert_tool_response(resp, "get_time")
    assert resp["error"] is False


def test_calculator_tool_smoke():
    from src.tools.tools import calculator

    resp = calculator.invoke({"expression": "2 + 3 * 4"})
    assert_tool_response(resp, "calculator")
    assert resp["error"] is False
    assert resp.get("data", {}).get("result") == "14"


def test_calculator_invalid_expression():
    from src.tools.tools import calculator

    resp = calculator.invoke({"expression": "not valid python"})
    assert_tool_response(resp, "calculator")
    assert resp["error"] is True


def test_calculator_dangerous_expression():
    """Test calculator rejects dangerous expressions with disallowed characters."""
    from src.tools.tools import calculator

    dangerous = [
        "import os",
        "__import__('os')",
        "exec('print(1)')",
        "eval('1+1')",
    ]

    for expr in dangerous:
        resp = calculator.invoke({"expression": expr})
        assert_tool_response(resp, "calculator")
        assert resp["error"] is True


@pytest.mark.parametrize(
    "tool_import_path, expected_name",
    [
        ("src.tools.tools:get_date", "get_date"),
        ("src.tools.tools:get_time", "get_time"),
        ("src.tools.tools:calculator", "calculator"),
    ],
)
def test_tools_are_langchain_tools(tool_import_path: str, expected_name: str):
    """Verify local tools conform to LangChain tool interface."""
    module_path, attr = tool_import_path.split(":", 1)
    mod = __import__(module_path, fromlist=[attr])
    tool_obj = getattr(mod, attr)

    # Basic LangChain tool interface check
    assert getattr(tool_obj, "name", None) == expected_name
    assert hasattr(tool_obj, "invoke")
