"""
Integration tests for MCP server.
"""

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_tools_loadable(mcp_server):
    """Test all tools can be loaded without errors."""
    tools = await mcp_server.list_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0

    # Each tool should be a Tool object with name and description
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert tool.name  # Name should not be empty
        assert tool.description  # Description should not be empty


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_names_unique(mcp_server):
    """Test all tool names are unique."""
    tools = await mcp_server.list_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names)), "Duplicate tool names found"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_names_no_mcp_prefix(mcp_server):
    """Test tool names don't have 'mcp_' prefix."""
    tools = await mcp_server.list_tools()
    for tool in tools:
        assert not tool.name.startswith("mcp_"), (
            f"Tool {tool.name} has mcp_ prefix"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tools_have_descriptions(mcp_server):
    """Test all tools have non-empty descriptions."""
    tools = await mcp_server.list_tools()
    for tool in tools:
        assert tool.description
        assert len(tool.description) > 10  # Should be meaningful


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expected_tools_present(mcp_server):
    """Test expected core tools are present."""
    tools = await mcp_server.list_tools()
    tool_names = [t.name for t in tools]

    expected_tools = [
        "get_time",
        "get_date",
        "calculator",
    ]

    for expected in expected_tools:
        assert expected in tool_names, f"Expected tool {expected} not found"


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_tools_callable(mcp_server):
    """Test tools can be invoked without errors."""
    tools = await mcp_server.list_tools()

    # Test simple tools that don't need arguments
    simple_tools = ["get_time", "get_date"]

    for tool in tools:
        if tool.name in simple_tools:
            # Should be able to call with empty dict
            try:
                result = await mcp_server.call_tool(tool.name, {})
                assert result is not None
            except Exception as e:
                pytest.fail(f"Tool {tool.name} failed to invoke: {e}")
