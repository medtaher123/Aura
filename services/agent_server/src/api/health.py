"""
Health Check Endpoint for Agent Server

Provides HTTP health check for ECS/ALB monitoring.
"""

import time
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel

from ..config import get_config

router = APIRouter()

# Track server start time for uptime calculation
_start_time = time.time()


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    service: str
    version: str
    uptime_seconds: float
    timestamp: str
    mcp_server_url: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint for load balancer and monitoring.
    
    Returns basic server status information.
    """
    config = get_config()
    
    return HealthResponse(
        status="healthy",
        service=config.name,
        version=config.version,
        uptime_seconds=round(time.time() - _start_time, 2),
        timestamp=datetime.now(timezone.utc).isoformat(),
        mcp_server_url=config.mcp_server_url,
    )
