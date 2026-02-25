"""
Agent Server - FastAPI Application Entry Point

Provides WebSocket-based API for agent orchestration.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_config
from .core.logger import get_logger, configure_log_level
from .api import health_router, websocket_router

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events.
    """
    # Startup
    config = get_config()
    configure_log_level(config.log_level)
    
    logger.info(f"Starting {config.name} v{config.version}")
    logger.info(f"MCP Server URL: {config.mcp_server_url}")
    logger.info(f"Bedrock Model: {config.bedrock_model_id}")
    
    # TODO: Pre-warm MCP connection and LLM client here
    
    yield
    
    # Shutdown
    logger.info("Shutting down Agent Server")


# Create FastAPI application
config = get_config()

app = FastAPI(
    title=config.name,
    description=config.description,
    version=config.version,
    lifespan=lifespan,
)

# Add CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(websocket_router)


@app.get("/")
async def root():
    """Root endpoint with basic service info."""
    return {
        "service": config.name,
        "version": config.version,
        "endpoints": {
            "health": "/health",
            "websocket": "/ws/chat",
        },
    }
