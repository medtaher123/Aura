"""
MCP Server - Official FastMCP SDK Implementation
Designed for AWS Fargate deployment with MCP protocol support
"""

from mcp_singleton import mcp
from starlette.requests import Request
from starlette.responses import JSONResponse
from datetime import datetime, timezone

from core.logger import get_logger
from config import get_config

logger = get_logger(__name__)
config = get_config()

# Initialize FastMCP server (exported for tools to use)
# mcp = get_server_instance()


_start_time = datetime.now()


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """
    Health check endpoint for AWS ALB/ECS health checks.
    Returns 200 if server is ready to accept requests.
    """
    try:
        tools = await mcp.list_tools()
        uptime = (datetime.now() - _start_time).total_seconds()

        return JSONResponse(
            {
                "status": "healthy",
                "service": "mcp-server",
                "tools_loaded": len(tools),
                "uptime_seconds": uptime,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return JSONResponse({"status": "unhealthy", "error": str(e)}, status_code=503)


def run_server():
    """Run the MCP server"""
    logger.info(f"Starting {config.name} v{config.version}")
    logger.info(f"Server running on {config.host}:{config.port}")
    logger.info("Using SSE transport for MCP")
    mcp.run(transport="sse")
    # load tools to ensure they are registered

    logger.info(f"Loaded {len(mcp.tools)} tools")


if __name__ == "__main__":
    run_server()
