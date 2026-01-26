import os
from datetime import date, datetime
from langchain.tools import tool
from .contracts import make_tool_response


@tool
def get_time() -> dict:
    """
    Get the current time in a human-readable string format.
    """
    current_time = datetime.now().strftime("%Hh%M")
    return make_tool_response(
        tool_name="get_time",
        message=f"The current time is {current_time}.",
        data={"time": current_time},
        error=False,
    )


@tool
def get_date() -> dict:
    """
    Get the current date in a human-readable string format.
    """
    #print("Debug: get_date called",date.today())
    current_date = date.today().strftime("%d/%m/%Y")
    #print(f"Debug: current_date = {current_date}")
    return make_tool_response(
        tool_name="get_date",
        message=f"Today's date is {current_date}.",
        data={"date": current_date},
        error=False,
    )


@tool
def calculator(expression: str) -> dict:
    """
    Evaluate a simple arithmetic expression (e.g., '23 * 7').
    Expected format: 'number operator number'
    """
    try:
        cleaned = expression.strip().replace(" ", "")
        allowed_chars = set("0123456789+-*/.() ")
        if not all(c in allowed_chars for c in cleaned):
            return make_tool_response(
                tool_name="calculator",
                message="Error: Disallowed characters in expression",
                data={"expression": expression},
                error=True,
            )
        result = str(eval(cleaned))
        return make_tool_response(
            tool_name="calculator",
            message=result,
            data={"expression": expression, "result": result},
            error=False,
        )
    except Exception:
        return make_tool_response(
            tool_name="calculator",
            message="Error: Invalid arithmetic expression",
            data={"expression": expression},
            error=True,
        )


def get_all_tools():
    """
    Return the list of all tools available to the agent.
    """
    try:
        from .mcp_remote_tools import get_mcp_tools

        tools = get_mcp_tools()
        print(f"Debug: Loaded {len(tools)} tools from MCP server.")
        print('loaded tools:', [tool.name for tool in tools])
    except Exception as e:
        raise RuntimeError(
            "Failed to load tools from MCP server. "
            "Ensure the MCP server is running and MCP_SERVER_URL is correct. "
            f"Details: {e}"
        )

    if not tools:
        raise RuntimeError(
            "MCP server returned zero tools. Ensure tools are registered in services/mcp_server/tools "
            "and the server is healthy (/health)."
        )

    return tools

