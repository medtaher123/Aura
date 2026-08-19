"""
Agent Server - FastAPI Application Entry Point

Provides WebSocket-based API for agent orchestration.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.auth.router import AuthRouter
from src.db.database import init_db
from src.files.router import FileStorageRouter

from .config import get_config
from .core.logger import get_logger, configure_log_level
from .api import health_router, conversations_router, websocket_router, files_router

logger = get_logger()


import os

if os.getenv("DEBUG", "false").lower() == "true":
    import debugpy
    try:
        # Listen on 0.0.0.0 so it's accessible from outside the container
        debugpy.listen(("0.0.0.0", 5678))
        print("✨ debugpy is listening on port 5678...")
        
        # Optional: Pause execution until the debugger attaches
        if os.getenv("DEBUG_WAIT_FOR_CLIENT", "false").lower() == "true":
            print("⏳ Waiting for debugger to attach...")
            debugpy.wait_for_client()
    except RuntimeError as e:
        # Catch the "Address already in use" error gracefully
        if "Address already in use" in str(e):
            print("⚡ debugpy is already active in the parent process. Skipping dual-binding.")
        else:
            raise e

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events.
    """
    # Startup
    config = get_config()
    configure_log_level(config.log_level)

    logger.info("Initializing database")
    await init_db()
    logger.info("Database initialized")
    
    logger.info(f"Starting {config.name} v{config.version}")
    logger.info(f"MCP Server URL: {config.mcp_server_url}")
    
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
app.include_router(conversations_router)
app.include_router(files_router)
app.include_router(websocket_router)

AuthRouter.initialize()
FileStorageRouter.initialize()


@app.get("/")
async def root():
    """Root endpoint with basic service info."""
    return {
        "service": config.name,
        "version": config.version,
        "endpoints": {
            "health": "/health",
            "websocket": "/ws/chat",
            "conversations": "/conversations",
            "files": "/files",
        },
    }
