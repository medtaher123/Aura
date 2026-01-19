from mcp.server.fastmcp import FastMCP
from config import get_config


def _get_server_instance() -> FastMCP:
    """Get the singleton FastMCP instance"""
    config = get_config()
    mcp = FastMCP(
        name=config.name,
        instructions=config.description,
        debug=config.log_level.upper() == "ERROR",
        log_level=config.log_level.upper(),
        host=config.host,
        port=config.port,
        json_response=True,
    )
    return mcp


mcp = _get_server_instance()
import tools  # noqa: E402, F403, F401
