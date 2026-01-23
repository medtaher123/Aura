"""
Tools module - Provides MCP-backed tools to the agent.

All tool implementations are served by the MCP server.
This module fetches them remotely and exposes them with a unified interface.
"""


def get_all_tools():
    """
    Return the list of all tools available to the agent.

    Tools are fetched from the MCP server. Raises RuntimeError if the server
    is unavailable or returns no tools.
    """
    from .mcp_remote_tools import get_mcp_tools

    try:
        tools = get_mcp_tools()
        print(f"Debug: Loaded {len(tools)} tools from MCP server.")
        print("loaded tools:", [tool.name for tool in tools])
    except Exception as e:
        raise RuntimeError(
            "Failed to load tools from MCP server. "
            "Ensure the MCP server is running and MCP_SERVER_URL is correct. "
            f"Details: {e}"
        )

    if not tools:
        raise RuntimeError(
            "MCP server returned zero tools. Ensure tools are registered in mcp_server service."
            "and the server is healthy (/health)."
        )

    return tools
