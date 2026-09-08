"""
Tests for Maxar Open Data imagery tool (single tool: country + year + optional month).

Uses pystac; tests mock pystac.Catalog.from_file and _open_event_collection.
_items_from_collection walks get_child_links() then _fetch_stac_with_requests for each child/item.

Run from services/mcp_server with project deps installed:

  pytest tests/test_tool_maxar_open_data.py -v
  pytest tests/test_tool_maxar_open_data.py -v -m "not slow"
"""

import pytest
from unittest.mock import Mock, patch

import pystac

from utils.contracts import ToolResponse


def _make_fake_root_catalog():
    """Build a mock pystac Catalog with child links for event IDs."""
    root = Mock()
    root.resolve_links = Mock()
    links = []
    for event_id in ("Hurricane-Ian-9-26-2022", "Brazil-Flooding-May24", "Kahramanmaras-turkey-earthquake-23"):
        link = Mock()
        link.get_absolute_href = Mock(return_value=f"https://example.com/events/{event_id}/collection.json")
        link.title = event_id
        link.target = link.get_absolute_href.return_value
        links.append(link)
    root.get_child_links = Mock(return_value=links)
    return root


def _make_fake_item():
    """Build a mock pystac Item with visual/thumbnail assets (used by _items_from_collection)."""
    asset_visual = Mock()
    asset_visual.get_absolute_href = Mock(return_value="https://example.com/cog/visual.tif")
    asset_thumb = Mock()
    asset_thumb.get_absolute_href = Mock(return_value="https://example.com/thumb.png")
    item = Mock()
    item.__class__ = pystac.Item
    item.id = "tile-001"
    item.bbox = [-48.0, -16.0, -47.0, -15.0]
    item.get_datetime = Mock(return_value=None)
    item.make_asset_hrefs_absolute = Mock()
    item.set_parent = Mock()
    item.get_assets = Mock(return_value={"visual": asset_visual, "thumbnail": asset_thumb})
    return item


def _make_fake_event_collection_with_items():
    """Build a mock Collection compatible with _items_from_collection: get_child_links() + child catalog + items."""
    coll = Mock()
    coll.title = "Brazil Flooding May 2024"
    coll.description = "Pre/post imagery."
    coll.self_href = "https://example.com/events/Brazil-Flooding-May24/collection.json"
    coll.get_root = Mock(return_value=coll)

    # One child link (sub-catalog); _items_from_collection will call _fetch_stac_with_requests(child_href)
    child_link = Mock()
    child_link.href = "sub/catalog.json"
    child_link.get_absolute_href = Mock(return_value="https://example.com/events/Brazil-Flooding-May24/sub/catalog.json")
    coll.get_child_links = Mock(return_value=[child_link])

    return coll


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maxar_imagery_tool_exists(mcp_client):
    """Single Maxar tool is registered."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "maxar_open_data_imagery_tool" in tool_names
    assert "maxar_open_data_events_tool" not in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maxar_imagery_tool_empty_country(mcp_client):
    """Imagery tool returns error when country is missing."""
    raw = await mcp_client.call_tool("maxar_open_data_imagery_tool", {"country": "", "year": 2024})
    result = ToolResponse.model_validate(raw)
    assert result.tool_name == "maxar_open_data_imagery_tool"
    assert result.error is True
    assert "country" in (result.message or "").lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maxar_imagery_tool_invalid_year(mcp_client):
    """Framework rejects non-integer year (Pydantic validation)."""
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError) as exc_info:
        await mcp_client.call_tool(
            "maxar_open_data_imagery_tool",
            {"country": "Brazil", "year": "not-a-year"},
        )
    assert "year" in str(exc_info.value).lower() or "integer" in str(exc_info.value).lower()


def _make_fake_child_catalog_with_item():
    """Mock child catalog returned by _fetch_stac_with_requests; has one item link."""
    child_cat = Mock()
    child_cat.__class__ = pystac.Catalog
    child_cat.self_href = "https://example.com/events/Brazil-Flooding-May24/sub/catalog.json"
    child_cat.set_root = Mock()
    child_cat.resolve_links = Mock()
    item_link = Mock()
    item_link.href = "item.json"
    item_link.get_absolute_href = Mock(return_value="https://example.com/events/Brazil-Flooding-May24/sub/item.json")
    child_cat.get_item_links = Mock(return_value=[item_link])
    return child_cat


@pytest.mark.unit
@pytest.mark.asyncio
@patch("modules.imagery.maxar_open_data._fetch_stac_with_requests")
@patch("modules.imagery.maxar_open_data._open_event_collection")
@patch("modules.imagery.maxar_open_data.pystac.Catalog.from_file")
async def test_maxar_imagery_tool_mocked(mock_from_file, mock_open_collection, mock_fetch_stac, mcp_client):
    """Imagery tool returns events and artifacts for country + year (pystac mocked)."""
    mock_from_file.return_value = _make_fake_root_catalog()
    mock_open_collection.return_value = _make_fake_event_collection_with_items()
    fake_item = _make_fake_item()

    def fetch_stac_side_effect(url):
        if "sub/catalog.json" in url or "sub/item.json" in url:
            if "item.json" in url:
                return fake_item
            return _make_fake_child_catalog_with_item()
        return None

    mock_fetch_stac.side_effect = fetch_stac_side_effect

    raw = await mcp_client.call_tool(
        "maxar_open_data_imagery_tool",
        {"country": "Brazil", "year": 2024},
    )
    result = ToolResponse.model_validate(raw)
    assert result.tool_name == "maxar_open_data_imagery_tool"
    assert result.error is False
    assert "Retrieved" in (result.message or "") or "imagery" in (result.message or "").lower()
    assert result.country == "Brazil"
    data = result.data or {}
    assert "event_ids" in data
    assert "Brazil-Flooding-May24" in data["event_ids"]
    assert "events" in data
    assert result.artifacts.urls or result.artifacts.thumbnails


@pytest.mark.unit
@pytest.mark.asyncio
@patch("modules.imagery.maxar_open_data.pystac.Catalog.from_file")
async def test_maxar_imagery_tool_no_match(mock_from_file, mcp_client):
    """Imagery tool returns no events when country/year match nothing."""
    mock_from_file.return_value = _make_fake_root_catalog()

    raw = await mcp_client.call_tool(
        "maxar_open_data_imagery_tool",
        {"country": "Mars", "year": 2030},
    )
    result = ToolResponse.model_validate(raw)
    assert result.error is False
    assert (result.data or {}).get("event_ids", []) == []
    assert "No Maxar" in (result.message or "") or "no" in (result.message or "").lower()


@pytest.mark.unit
@pytest.mark.asyncio
@patch("modules.imagery.maxar_open_data.pystac.Catalog.from_file")
async def test_maxar_imagery_tool_catalog_unavailable(mock_from_file, mcp_client):
    """When catalog load fails, tool returns no events."""
    mock_from_file.side_effect = Exception("timeout")
    raw = await mcp_client.call_tool(
        "maxar_open_data_imagery_tool",
        {"country": "Brazil", "year": 2024},
    )
    result = ToolResponse.model_validate(raw)
    assert result.error is False
    assert (result.data or {}).get("event_ids", []) == []
    assert "No Maxar" in (result.message or "") or "no event" in (result.message or "").lower()


@pytest.mark.unit
def test_get_event_ids_by_location_and_date():
    """Normal function returns matching event IDs (pystac root mocked)."""
    from modules.imagery.maxar_open_data import get_event_ids_by_location_and_date

    with patch("modules.imagery.maxar_open_data.pystac.Catalog.from_file") as mock_from_file:
        mock_from_file.return_value = _make_fake_root_catalog()
        ids = get_event_ids_by_location_and_date("Brazil", 2024)
        assert "Brazil-Flooding-May24" in ids
        mock_from_file.return_value = _make_fake_root_catalog()
        ids_turkey = get_event_ids_by_location_and_date("Turkey", 2023)
        assert "Kahramanmaras-turkey-earthquake-23" in ids_turkey
        mock_from_file.return_value = _make_fake_root_catalog()
        ids_none = get_event_ids_by_location_and_date("Mars", 2030)
        assert ids_none == []


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.slow
async def test_maxar_imagery_tool_live(mcp_client):
    """Call real catalog with country + year (slow, requires network). Skipped in CI unless integration tests run."""
    raw = await mcp_client.call_tool(
        "maxar_open_data_imagery_tool",
        {"country": "Brazil", "year": 2024, "max_events": 2},
    )
    result = ToolResponse.model_validate(raw)
    assert result.tool_name == "maxar_open_data_imagery_tool"
    if result.error:
        return
    assert "event_ids" in (result.data or {})
    assert "country" in (result.data or {})
