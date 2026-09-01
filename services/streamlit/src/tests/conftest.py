"""
Pytest configuration and shared fixtures for streamlit service tests.
"""

import pytest

from models import ToolCoordinates, ToolResponse, ToolArtifacts
from clients import ChatMessage


@pytest.fixture
def sample_tool_response() -> ToolResponse:
    """Create a sample ToolResponse for testing."""

    return ToolResponse(
        tool_name="test_tool",
        message="Test message",
        artifacts=ToolArtifacts(maps=[{"title": "test", "view_state": {"latitude": 0, "longitude": 0, "zoom": 1}, "layers": []}], thumbnails=[], urls=[]),
        start_date="2024-01-01",
        end_date="2024-12-31",
        country="France",
        city="Paris",
        coordinates=ToolCoordinates(lat=48.8566, lon=2.3522),
        data={"test_key": "test_value"},
        error=False,
    )


@pytest.fixture
def sample_chat_history():
    """Create a sample chat history for testing."""
    return [
        ChatMessage(role="user", content="Show me fires in Berlin in 2024"),
        ChatMessage(role="assistant", content="I found 10 fires in Berlin in 2024."),
        ChatMessage(role="user", content="What about Paris?"),
        ChatMessage(role="assistant", content="Paris had 5 fires in 2024."),
    ]


@pytest.fixture
def mock_llm_message():
    """Create a mock LLM message class."""

    class MockMessage:
        def __init__(self, content: str):
            self.content = content

    return MockMessage
