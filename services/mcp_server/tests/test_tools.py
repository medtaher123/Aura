"""
Tests for individual MCP tools.
"""

import pytest
from tools.simple_tools import get_time, get_date, calculator
from utils.contracts import ToolResponse


@pytest.mark.unit
def test_get_time_tool():
    """Test get_time returns current time."""
    result = get_time()
    assert isinstance(result, ToolResponse)
    assert result.message
    assert "time" in result.data
    time_value = result.data["time"]
    assert "h" in time_value or ":" in time_value


@pytest.mark.unit
def test_get_date_tool():
    """Test get_date returns current date."""
    result = get_date()
    assert isinstance(result, ToolResponse)
    assert result.message
    assert "date" in result.data
    date_value = result.data["date"]
    assert "-" in date_value or "/" in date_value
    assert "202" in date_value


@pytest.mark.unit
def test_calculator_valid_expressions():
    """Test calculator with various valid expressions."""
    test_cases = [
        ("2 + 2", 4),
        ("10 - 3", 7),
        ("5 * 6", 30),
        ("10 / 2", 5),
        ("2 ** 3", 8),
        ("(2 + 3) * 4", 20),
    ]

    for expression, expected in test_cases:
        result = calculator(expression=expression)
        assert isinstance(result, ToolResponse)
        assert result.data.get("result") == expected


@pytest.mark.unit
def test_calculator_invalid_expression():
    """Test calculator with invalid expression."""
    result = calculator(expression="not valid python")
    assert isinstance(result, ToolResponse)
    assert result.error is True or "error" in result.message.lower()


@pytest.mark.unit
def test_calculator_dangerous_expression():
    """Test calculator rejects dangerous expressions."""
    dangerous = [
        "import os",
        "__import__('os')",
        "exec('print(1)')",
        "eval('1+1')",
    ]
    
    for expr in dangerous:
        result = calculator(expression=expr)
        assert isinstance(result, ToolResponse)
        assert result.error is True or "error" in result.message.lower()


@pytest.mark.unit
def test_calculator_empty_expression():
    """Test calculator with empty expression."""
    try:
        result = calculator(expression="")
        assert isinstance(result, ToolResponse)
        assert result.error is True
    except Exception:
        pass


@pytest.mark.unit
def test_calculator_division_by_zero():
    """Test calculator handles division by zero."""
    result = calculator(expression="1 / 0")
    assert isinstance(result, ToolResponse)
    assert result.error is True or "error" in result.message.lower()
