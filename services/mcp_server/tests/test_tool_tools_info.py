"""
Tests for tools_info_tool
"""

import pytest
from tools.tools_info import tools_info_tool
from utils.contracts import ToolResponse


def _as_dict(resp):
    """Convert ToolResponse (or other) to dict for assertions."""
    if hasattr(resp, "model_dump"):
        return resp.model_dump(mode="json")
    return resp


def test_list_all_tools():
    """Test listing all available tools"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(list_all=True))

    assert result["error"] is False
    assert "tools" in result["data"]
    assert "categories" in result["data"]
    assert result["data"]["total_tools"] > 0
    assert "Available Tools" in result["message"]
=======
    result = tools_info_tool(list_all=True)
    
    assert result.error is False
    assert "tools" in result.data
    assert "categories" in result.data
    assert result.data["total_tools"] > 0
    assert "Available Tools" in result.message
>>>>>>> main


def test_specific_tool_info():
    """Test getting info about a specific tool"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(tool_name="detect_fire_tool"))

    assert result["error"] is False
    assert "tool_id" in result["data"]
    assert result["data"]["tool_id"] == "detect_fire_tool"
    assert "Fire Detection Tool" in result["message"]
    assert "NASA FIRMS" in result["message"]
    assert "Example Questions" in result["message"]
=======
    result = tools_info_tool(tool_name="detect_fire_tool")
    
    assert result.error is False
    assert "tool_id" in result.data
    assert result.data["tool_id"] == "detect_fire_tool"
    assert "Fire Detection Tool" in result.message
    assert "NASA FIRMS" in result.message
    assert "Example Questions" in result.message
>>>>>>> main


def test_tool_not_found():
    """Test handling of non-existent tool"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(tool_name="nonexistent_tool"))

    assert result["error"] is True
    assert "not found" in result["message"]
    assert "available_tools" in result["data"]
=======
    result = tools_info_tool(tool_name="nonexistent_tool")
    
    assert result.error is True
    assert "not found" in result.message
    assert "available_tools" in result.data
>>>>>>> main


def test_category_listing():
    """Test listing tools by category"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(category="Weather & Climate"))

    assert result["error"] is False
    assert "category" in result["data"]
    assert "Weather & Climate" in result["message"]
    assert "tools" in result["data"]
    assert len(result["data"]["tools"]) > 0
=======
    result = tools_info_tool(category="Weather & Climate")
    
    assert result.error is False
    assert "category" in result.data
    assert "Weather & Climate" in result.message
    assert "tools" in result.data
    assert len(result.data["tools"]) > 0
>>>>>>> main


def test_category_partial_match():
    """Test category search with partial match"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(category="weather"))

    assert result["error"] is False
    assert "Weather & Climate" in result["data"]["category"]
=======
    result = tools_info_tool(category="weather")
    
    assert result.error is False
    assert "Weather & Climate" in result.data["category"]
>>>>>>> main


def test_category_not_found():
    """Test handling of non-existent category"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(category="nonexistent category"))

    assert result["error"] is True
    assert "not found" in result["message"]
    assert "available_categories" in result["data"]
=======
    result = tools_info_tool(category="nonexistent category")
    
    assert result.error is True
    assert "not found" in result.message
    assert "available_categories" in result.data
>>>>>>> main


def test_query_fire_detection():
    """Test natural language query for fire detection"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(query="fire detection"))

    assert result["error"] is False
    assert "relevant_tools" in result["data"]
    assert "detect_fire_tool" in result["data"]["relevant_tools"]
    assert "match_count" in result["data"]
=======
    result = tools_info_tool(query="fire detection")
    
    assert result.error is False
    assert "relevant_tools" in result.data
    assert "detect_fire_tool" in result.data["relevant_tools"]
    assert "match_count" in result.data
>>>>>>> main


def test_query_weather():
    """Test natural language query for weather"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(query="weather forecast"))

    assert result["error"] is False
    assert "relevant_tools" in result["data"]
    assert "weather_tool" in result["data"]["relevant_tools"]
=======
    result = tools_info_tool(query="weather forecast")
    
    assert result.error is False
    assert "relevant_tools" in result.data
    assert "weather_tool" in result.data["relevant_tools"]
>>>>>>> main


def test_query_satellite():
    """Test natural language query for satellite imagery"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(query="satellite images"))

    assert result["error"] is False
    assert "relevant_tools" in result["data"]
    assert "query_stac_catalog" in result["data"]["relevant_tools"]
=======
    result = tools_info_tool(query="satellite images")
    
    assert result.error is False
    assert "relevant_tools" in result.data
    assert "query_stac_catalog" in result.data["relevant_tools"]
>>>>>>> main


def test_query_no_match():
    """Test query with no matching tools"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(query="quantum computing"))

    assert result["error"] is False  # Not an error, just no results
    assert "No tools found" in result["message"]
=======
    result = tools_info_tool(query="quantum computing")
    
    assert result.error is False
    assert "No tools found" in result.message
>>>>>>> main


def test_default_help():
    """Test default help message when no parameters provided"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool())

    assert result["error"] is False
    assert "Tools Information Assistant" in result["message"]
    assert "How to use" in result["message"]
    assert "Available categories" in result["message"]
=======
    result = tools_info_tool()
    
    assert result.error is False
    assert "Tools Information Assistant" in result.message
    assert "How to use" in result.message
    assert "Available categories" in result.message
>>>>>>> main


def test_query_what_tools_available():
    """Test common question 'what tools are available'"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(query="what tools are available"))

    assert result["error"] is False
    assert "Available Tools" in result["message"]
    assert "total_tools" in result["data"]
=======
    result = tools_info_tool(query="what tools are available")
    
    assert result.error is False
    assert "Available Tools" in result.message
    assert "total_tools" in result.data
>>>>>>> main


def test_query_list_all_variant():
    """Test variant of list all query"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(query="list all tools"))

    assert result["error"] is False
    assert "Available Tools" in result["message"]
    assert "total_tools" in result["data"]
=======
    result = tools_info_tool(query="list all tools")
    
    assert result.error is False
    assert "Available Tools" in result.message
    assert "total_tools" in result.data
>>>>>>> main


def test_tool_info_weather_tool():
    """Test detailed info for weather tool"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(tool_name="weather_tool"))

    assert result["error"] is False
    assert "Weather Tool" in result["message"]
    assert "Open-Meteo" in result["message"]
    assert "Parameters:" in result["message"]
    assert "city_name" in result["message"]
=======
    result = tools_info_tool(tool_name="weather_tool")
    
    assert result.error is False
    assert "Weather Tool" in result.message
    assert "Open-Meteo" in result.message
    assert "Parameters:" in result.message
    assert "city_name" in result.message
>>>>>>> main


def test_tool_info_with_partial_name():
    """Test tool lookup with partial name"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(tool_name="fire"))

    assert result["error"] is False
    assert "detect_fire_tool" in result["data"]["tool_id"]
=======
    result = tools_info_tool(tool_name="fire")
    
    assert result.error is False
    assert "detect_fire_tool" in result.data["tool_id"]
>>>>>>> main


def test_streamflow_tool_info():
    """Test info for streamflow tool"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(tool_name="streamflow_forecast_tool"))

    assert result["error"] is False
    assert "GEOGLOWS" in result["message"]
    assert "river discharge" in result["message"].lower()
=======
    result = tools_info_tool(tool_name="streamflow_forecast_tool")
    
    assert result.error is False
    assert "GEOGLOWS" in result.message
    assert "river discharge" in result.message.lower()
>>>>>>> main


def test_nasa_power_tools():
    """Test query for NASA POWER tools"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(query="NASA POWER climate data"))

    assert result["error"] is False
    assert any("nasa_power" in tool for tool in result["data"]["relevant_tools"])
=======
    result = tools_info_tool(query="NASA POWER climate data")
    
    assert result.error is False
    assert any("nasa_power" in tool for tool in result.data["relevant_tools"])
>>>>>>> main


def test_infrastructure_category():
    """Test Infrastructure & Geography category"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(category="Infrastructure"))

    assert result["error"] is False
    assert "Infrastructure & Geography" in result["data"]["category"]
    assert "infrastructure_query_tool" in result["data"]["tools"]
=======
    result = tools_info_tool(category="Infrastructure")
    
    assert result.error is False
    assert "Infrastructure & Geography" in result.data["category"]
    assert "infrastructure_query_tool" in result.data["tools"]
>>>>>>> main


def test_utilities_category():
    """Test Utilities category"""
<<<<<<< test_tools_KPIs
    result = _as_dict(tools_info_tool(category="Utilities"))

    assert result["error"] is False
    assert "Utilities" in result["data"]["category"]
    assert "calculator" in result["data"]["tools"]
    assert "get_time" in result["data"]["tools"]
    assert "get_date" in result["data"]["tools"]
=======
    result = tools_info_tool(category="Utilities")
    
    assert result.error is False
    assert "Utilities" in result.data["category"]
    assert "calculator" in result.data["tools"]
    assert "get_time" in result.data["tools"]
    assert "get_date" in result.data["tools"]
>>>>>>> main
