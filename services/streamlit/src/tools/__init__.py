"""
Tools module - Provides MCP-backed tools to the agent.

All tool implementations are served by the MCP server (services/mcp_server).
This module provides:
- get_all_tools(): Fetch all available tools from the MCP server
- MCPRemoteTool: Wrapper class for invoking MCP tools
- ToolResponse, make_tool_response: Standardized response contracts
"""

from .tools import get_all_tools
from .mcp_remote_tools import get_mcp_tools, MCPRemoteTool
from .contracts import ToolResponse, make_tool_response

__all__ = [
    "get_all_tools",
    "get_mcp_tools",
    "MCPRemoteTool",
    "ToolResponse",
    "make_tool_response",
]
