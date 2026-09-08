"""Built-in native tools."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from src.tools.contracts import ToolResponse
from src.tools.native.base import NativeTool

_MAX_WAIT_SECONDS = 300.0


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

#TODO: to remove or set only in dev mode
class WaitTool(NativeTool):
    """Wait for a given number of seconds before continuing.

    Useful for pacing, polling gaps, or testing parallel tool execution.
    """

    tool_name = "wait"

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": (
                        "How long to wait, in seconds "
                        f"(0–{_MAX_WAIT_SECONDS:g})."
                    ),
                    "minimum": 0,
                    "maximum": _MAX_WAIT_SECONDS,
                }
            },
            "required": ["seconds"],
        }

    async def invoke(self, seconds: float | int | str = 0, **kwargs: Any) -> ToolResponse:
        try:
            delay = float(seconds)
        except (TypeError, ValueError):
            return ToolResponse(
                tool_name=self.tool_name,
                message=f"Invalid seconds value: {seconds!r}",
                data={"seconds": seconds},
                error=True,
            )
        if delay < 0:
            return ToolResponse(
                tool_name=self.tool_name,
                message="seconds must be >= 0",
                data={"seconds": delay},
                error=True,
            )
        if delay > _MAX_WAIT_SECONDS:
            return ToolResponse(
                tool_name=self.tool_name,
                message=f"seconds must be <= {_MAX_WAIT_SECONDS:g}",
                data={"seconds": delay, "max_seconds": _MAX_WAIT_SECONDS},
                error=True,
            )

        await asyncio.sleep(delay)
        return ToolResponse(
            tool_name=self.tool_name,
            message=f"Waited {delay:g} second{'s' if delay != 1 else ''}.",
            data={"seconds": delay},
            error=False,
        )
