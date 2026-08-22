"""In-process native tools."""

from datetime import date, datetime

from src.tools.contracts import ToolResponse
from src.tools.native.decorator import native_tool


@native_tool
def get_time() -> ToolResponse:
    """
    Get the current time in a human-readable string format.
    """
    current_time = datetime.now().strftime("%Hh%M")
    return ToolResponse(
        tool_name="get_time",
        message=f"The current time is {current_time}.",
        data={"time": current_time},
        error=False,
    )


@native_tool
def get_date() -> ToolResponse:
    """
    Get the current date in a human-readable string format.
    """
    current_date = date.today().strftime("%d/%m/%Y")
    return ToolResponse(
        tool_name="get_date",
        message=f"Today's date is {current_date}.",
        data={"date": current_date},
        error=False,
    )


@native_tool
def calculator(expression: str) -> ToolResponse:
    """
    Evaluate a simple arithmetic expression (e.g., '23 * 7').
    Expected format: 'number operator number'
    """
    try:
        cleaned = expression.strip().replace(" ", "")
        allowed_chars = set("0123456789+-*/.() ")
        if not all(c in allowed_chars for c in cleaned):
            return ToolResponse(
                tool_name="calculator",
                message="Error: Disallowed characters in expression",
                data={"expression": expression},
                error=True,
            )
        result = str(eval(cleaned))
        return ToolResponse(
            tool_name="calculator",
            message=result,
            data={"expression": expression, "result": result},
            error=False,
        )
    except Exception:
        return ToolResponse(
            tool_name="calculator",
            message="Error: Invalid arithmetic expression",
            data={"expression": expression},
            error=True,
        )
