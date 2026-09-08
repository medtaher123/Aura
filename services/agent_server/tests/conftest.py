"""
Pytest configuration and fixtures for Agent Server tests.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.config import get_config


@pytest.fixture(scope="session", autouse=True)
def _init_graph_checkpointer():
    from src.services.graph_runner.checkpointer import init_checkpointer, shutdown_checkpointer

    asyncio.run(init_checkpointer())
    yield
    asyncio.run(shutdown_checkpointer())


@pytest.fixture
def client():
    """Synchronous test client for HTTP endpoints."""
    return TestClient(app)


@pytest.fixture
async def async_client():
    """Async test client for WebSocket testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def config():
    """Get server configuration."""
    return get_config()
