"""
Tests for tools_info_tool
"""

import pytest
from tools.tools_info import tools_info_tool
from utils.contracts import ToolResponse


def test_list_all_tools():
    """Test listing all available tools"""
    result = tools_info_tool(list_all=True)
    
    assert result.error is False
    assert "tools" in result.data
    assert "categories" in result.data
    assert result.data["total_tools"] > 0
    assert "Available Tools" in result.message


def test_specific_tool_info():
    """Test getting info about a specific tool"""
    result = tools_info_tool(tool_name="detect_fire_tool")
    
    assert result.error is False
    assert "tool_id" in result.data
    assert result.data["tool_id"] == "detect_fire_tool"
    assert "Fire Detection Tool" in result.message
    assert "NASA FIRMS" in result.message
    assert "Example Questions" in result.message


def test_tool_not_found():
    """Test handling of non-existent tool"""
    result = tools_info_tool(tool_name="nonexistent_tool")
    
    assert result.error is True
    assert "not found" in result.message
    assert "available_tools" in result.data


def test_category_listing():
    """Test listing tools by category"""
    result = tools_info_tool(category="Weather & Climate")
    
    assert result.error is False
    assert "category" in result.data
    assert "Weather & Climate" in result.message
    assert "tools" in result.data
    assert len(result.data["tools"]) > 0


def test_category_partial_match():
    """Test category search with partial match"""
    result = tools_info_tool(category="weather")
    
    assert result.error is False
    assert "Weather & Climate" in result.data["category"]


def test_category_not_found():
    """Test handling of non-existent category"""
    result = tools_info_tool(category="nonexistent category")
    
    assert result.error is True
    assert "not found" in result.message
    assert "available_categories" in result.data


def test_query_fire_detection():
    """Test natural language query for fire detection"""
    result = tools_info_tool(query="fire detection")
    
    assert result.error is False
    assert "relevant_tools" in result.data
    assert "detect_fire_tool" in result.data["relevant_tools"]
    assert "match_count" in result.data


def test_query_weather():
    """Test natural language query for weather"""
    result = tools_info_tool(query="weather forecast")
    
    assert result.error is False
    assert "relevant_tools" in result.data
    assert "weather_tool" in result.data["relevant_tools"]


def test_query_satellite():
    """Test natural language query for satellite imagery"""
    result = tools_info_tool(query="satellite images")
    
    assert result.error is False
    assert "relevant_tools" in result.data
    assert "query_stac_catalog" in result.data["relevant_tools"]


def test_query_no_match():
    """Test query with no matching tools"""
    result = tools_info_tool(query="quantum computing")
    
    assert result.error is False
    assert "No tools found" in result.message


def test_default_help():
    """Test default help message when no parameters provided"""
    result = tools_info_tool()
    
    assert result.error is False
    assert "Tools Information Assistant" in result.message
    assert "How to use" in result.message
    assert "Available categories" in result.message


def test_query_what_tools_available():
    """Test common question 'what tools are available'"""
    result = tools_info_tool(query="what tools are available")
    
    assert result.error is False
    assert "Available Tools" in result.message
    assert "total_tools" in result.data


def test_query_list_all_variant():
    """Test variant of list all query"""
    result = tools_info_tool(query="list all tools")
    
    assert result.error is False
    assert "Available Tools" in result.message
    assert "total_tools" in result.data


def test_query_what_tools_about_floods():
    """Scoped tool questions should search, not dump the full catalog."""
    result = tools_info_tool(query="what tools do you have about floods")

    assert result.error is False
    assert "relevant_tools" in result.data
    assert "Available Tools" not in result.message
    relevant = result.data["relevant_tools"]
    assert any(
        tool in relevant
        for tool in (
            "streamflow_forecast_tool",
            "flood_depth_damage_tool",
            "estimate_surface_water_ingress_tool",
            "drought_flood_risk_tool",
        )
    )


def test_tool_info_weather_tool():
    """Test detailed info for weather tool"""
    result = tools_info_tool(tool_name="weather_tool")
    
    assert result.error is False
    assert "Weather Tool" in result.message
    assert "Open-Meteo" in result.message
    assert "Parameters:" in result.message
    assert "city_name" in result.message


def test_tool_info_with_partial_name():
    """Test tool lookup with partial name"""
    result = tools_info_tool(tool_name="fire")
    
    assert result.error is False
    assert "detect_fire_tool" in result.data["tool_id"]


def test_streamflow_tool_info():
    """Test info for streamflow tool"""
    result = tools_info_tool(tool_name="streamflow_forecast_tool")
    
    assert result.error is False
    assert "GEOGLOWS" in result.message
    assert "river discharge" in result.message.lower()


def test_nasa_power_tools():
    """Test query for NASA POWER tools"""
    result = tools_info_tool(query="NASA POWER climate data")
    
    assert result.error is False
    assert any("nasa_power" in tool for tool in result.data["relevant_tools"])


def test_infrastructure_category():
    """Test Infrastructure & Geography category"""
    result = tools_info_tool(category="Infrastructure")
    
    assert result.error is False
    assert "Infrastructure & Geography" in result.data["category"]
    assert "infrastructure_query_tool" in result.data["tools"]
    assert "bdtopo_query_tool" in result.data["tools"]
    assert "bdtopo_intersection_tool" in result.data["tools"]
    assert "bdtopo_coverage_quality_tool" in result.data["tools"]
    assert "bdtopo_change_snapshot_tool" in result.data["tools"]
    assert "bdtopo_thematic_explain_tool" in result.data["tools"]


def test_bdtopo_tool_info():
    """Test tool info for BDTOPO query tool."""
    result = tools_info_tool(tool_name="bdtopo_query_tool")

    assert result.error is False
    assert "BDTOPO PostGIS Query Tool" in result.message
    assert "query_type" in result.message


def test_utilities_category():
    """Test Utilities category"""
    result = tools_info_tool(category="Utilities")
    
    assert result.error is False
    assert "Utilities" in result.data["category"]
    assert "calculator" in result.data["tools"]
    assert "get_time" in result.data["tools"]
    assert "get_date" in result.data["tools"]
