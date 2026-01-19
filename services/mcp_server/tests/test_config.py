"""
Tests for MCP server configuration.
"""

import pytest
from config import MCPServerConfig, get_config


@pytest.mark.unit
def test_config_instance():
    """Test config is properly instantiated."""
    config = get_config()
    assert isinstance(config, MCPServerConfig)


@pytest.mark.unit
def test_config_has_required_fields():
    """Test config has all required fields."""
    config = get_config()
    assert hasattr(config, "host")
    assert hasattr(config, "port")
    assert hasattr(config, "log_level")
    assert hasattr(config, "name")


@pytest.mark.unit
def test_config_defaults():
    """Test config default values are sensible."""
    config = get_config()
    assert config.host == "0.0.0.0"
    assert config.port == 8000
    assert config.log_level.lower() in ["debug", "info", "warning", "error"]


@pytest.mark.unit
def test_config_singleton():
    """Test get_config returns same instance."""
    config1 = get_config()
    config2 = get_config()
    assert config1 is config2


@pytest.mark.unit
def test_config_validation():
    """Test config validates port range."""
    # Valid port
    config = MCPServerConfig(port=8080)
    assert config.port == 8080
