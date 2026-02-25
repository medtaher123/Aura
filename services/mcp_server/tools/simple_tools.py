"""
Simple Tools for MCP Server

This module contains simple tools with no external service dependencies.
"""

from mcp_singleton import mcp
from datetime import date, datetime
from utils.contracts import ToolResponse


@mcp.tool()
def get_time() -> ToolResponse:
    """Get the current time in a human-readable string format."""
    current_time = datetime.now().strftime("%Hh%M")
    return ToolResponse(
        tool_name="get_time",
        message=f"The current time is {current_time}.",
        data={"time": current_time},
        error=False,
    )


@mcp.tool()
def get_date() -> ToolResponse:
    """Get the current date in a human-readable string format."""
    current_date = date.today().strftime("%d/%m/%Y")
    return ToolResponse(
        tool_name="get_date",
        message=f"Today's date is {current_date}.",
        data={"date": current_date},
        error=False,
    )


@mcp.tool()
def calculator(expression: str) -> ToolResponse:
    """Evaluate a simple arithmetic expression (e.g., '23 * 7')."""
    print("TOOOO")
    try:
        allowed_chars = set("0123456789+-*/()%. ")
        if not all(c in allowed_chars for c in expression):
            raise ValueError("Invalid characters in expression")

        result = eval(expression, {"__builtins__": {}}, {})
        return ToolResponse(
            tool_name="calculator",
            message=f"Result: {result}",
            data={"expression": expression, "result": result},
            error=False,
        )
    except Exception as e:
        return ToolResponse(
            tool_name="calculator",
            message=f"Error evaluating expression: {str(e)}",
            data={"expression": expression},
            error=True,
        )
