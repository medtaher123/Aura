"""
Simple MCP Client for testing the SSE MCP Server
Uses FastMCP client to connect and test available tools
"""

import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client
from config import get_config

config = get_config()


async def test_mcp_server():
    """Test the MCP server connection and tools"""

    # Server URL for SSE connection
    server_url = f"http://{config.host}:{config.port}/sse"

    print(f"Connecting to MCP server at {server_url}")

    try:
        # Create SSE client connection
        async with sse_client(server_url) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                await session.initialize()
                print("✓ Connected to MCP server")

                # List available tools
                tools_result = await session.list_tools()
                tools = tools_result.tools
                print(f"✓ Found {len(tools)} available tools:")

                for tool in tools:
                    print(f"  - {tool.name}: {tool.description}")

                # Test calling a simple tool (if available)
                if tools:
                    test_tool = tools[0]
                    print(f"\n🧪 Testing tool: {test_tool.name}")

                    # Prepare minimal arguments based on tool schema
                    test_args = {}
                    if hasattr(test_tool, "inputSchema") and test_tool.inputSchema:
                        schema = test_tool.inputSchema
                        if "properties" in schema:
                            # Add sample values for required fields
                            for prop_name, prop_info in schema["properties"].items():
                                if prop_name in schema.get("required", []):
                                    # Provide sample values based on type
                                    if prop_info.get("type") == "string":
                                        test_args[prop_name] = "test"
                                    elif prop_info.get("type") == "number":
                                        test_args[prop_name] = 0
                                    elif prop_info.get("type") == "array":
                                        test_args[prop_name] = []

                    try:
                        result = await session.call_tool(test_tool.name, test_args)
                        print(
                            f"✓ Tool response: {result.content[:200] if result.content else 'No content'}"
                        )
                    except Exception as e:
                        print(f"⚠ Tool call failed (expected if args incomplete): {e}")

                print("\n✅ MCP Client test completed successfully")

    except Exception as e:
        print(f"❌ Error testing MCP server: {e}")
        raise


async def list_tools_only():
    """Simple function to just list available tools"""
    server_url = f"http://{config.host}:{config.port}/sse"

    async with sse_client(server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()

            print(f"\n{'=' * 60}")
            print(f"Available Tools ({len(tools_result.tools)}):")
            print(f"{'=' * 60}\n")

            for i, tool in enumerate(tools_result.tools, 1):
                print(f"{i}. {tool.name}")
                print(f"   Description: {tool.description}")
                if hasattr(tool, "inputSchema") and tool.inputSchema:
                    required = tool.inputSchema.get("required", [])
                    if required:
                        print(f"   Required params: {', '.join(required)}")
                print()


async def call_tool(tool_name: str, **kwargs):
    """Call a specific tool with arguments"""
    server_url = f"http://{config.host}:{config.port}/sse"

    async with sse_client(server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print(f"Calling tool: {tool_name}")
            print(f"Arguments: {kwargs}")

            result = await session.call_tool(tool_name, kwargs)

            print(f"\n{'=' * 60}")
            print(f"Tool: {tool_name}")
            print(f"{'=' * 60}")
            print(f"Result: {result.content[0].model_dump(mode='json')['text']}")
            print()

            return result


def main():
    """Main entry point"""
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "list":
            asyncio.run(list_tools_only())
        elif command == "call" and len(sys.argv) > 2:
            tool_name = sys.argv[2]
            # Parse additional args as key=value pairs
            args = {}
            for arg in sys.argv[3:]:
                if "=" in arg:
                    key, value = arg.split("=", 1)
                    args[key] = value
            asyncio.run(call_tool(tool_name, **args))
        else:
            print("Usage:")
            print("  python test_mcp_client.py           # Run full test")
            print("  python test_mcp_client.py list      # List all tools")
            print("  python test_mcp_client.py call <tool_name> [key=value ...]")
    else:
        # Run full test
        asyncio.run(test_mcp_server())


if __name__ == "__main__":
    main()
