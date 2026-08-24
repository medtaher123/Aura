"""Built-in native tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.tools.contracts import ToolResponse
from src.tools.native.base import NativeTool


class GetTimeTool(NativeTool):
    """Get the current time in a human-readable string format."""

    tool_name = "get_time"

    def invoke(self, **kwargs: Any) -> ToolResponse:
        current_time = datetime.now().strftime("%Hh%M")
        return ToolResponse(
            tool_name=self.tool_name,
            message=f"The current time is {current_time}.",
            data={"time": current_time},
            error=False,
        )


class GetDateTool(NativeTool):
    """Get the current date in a human-readable string format."""

    tool_name = "get_date"

    def invoke(self, **kwargs: Any) -> ToolResponse:
        current_date = date.today().strftime("%d/%m/%Y")
        return ToolResponse(
            tool_name=self.tool_name,
            message=f"Today's date is {current_date}.",
            data={"date": current_date},
            error=False,
        )


class CalculatorTool(NativeTool):
    """Evaluate a simple arithmetic expression (e.g., '23 * 7')."""

    tool_name = "calculator"

    def invoke(self, expression: str = "", **kwargs: Any) -> ToolResponse:
        try:
            cleaned = expression.strip().replace(" ", "")
            allowed_chars = set("0123456789+-*/.() ")
            if not all(c in allowed_chars for c in cleaned):
                return ToolResponse(
                    tool_name=self.tool_name,
                    message="Error: Disallowed characters in expression",
                    data={"expression": expression},
                    error=True,
                )
            result = str(eval(cleaned))
            return ToolResponse(
                tool_name=self.tool_name,
                message=result,
                data={"expression": expression, "result": result},
                error=False,
            )
        except Exception:
            return ToolResponse(
                tool_name=self.tool_name,
                message="Error: Invalid arithmetic expression",
                data={"expression": expression},
                error=True,
            )
