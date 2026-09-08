"""Unit tests for MCP Streamable HTTP transport helpers."""

from __future__ import annotations

from types import SimpleNamespace

from eo_llm.adapters.mcp_transport import (
    extract_tool_payload,
    mcp_streamable_http_url,
    tool_input_schema,
    tool_metadata_from_mcp_tool,
)


def test_mcp_streamable_http_url_appends_mcp():
    assert mcp_streamable_http_url("http://mcp-server:8000") == "http://mcp-server:8000/mcp"
    assert mcp_streamable_http_url("http://localhost:8000/") == "http://localhost:8000/mcp"


def test_mcp_streamable_http_url_preserves_mcp_suffix():
    assert (
        mcp_streamable_http_url("http://mcp-server:8000/mcp")
        == "http://mcp-server:8000/mcp"
    )


def test_mcp_streamable_http_url_skips_append_when_disabled():
    assert (
        mcp_streamable_http_url(
            "https://mcp.pappers.fr/abc",
            append_mcp_path=False,
        )
        == "https://mcp.pappers.fr/abc"
    )


def test_tool_input_schema_prefers_snake_case():
    tool = SimpleNamespace(
        input_schema={"type": "object", "properties": {"lat": {"type": "number"}}},
        inputSchema={"type": "object", "properties": {"old": {"type": "string"}}},
    )
    schema = tool_input_schema(tool)
    assert "lat" in schema["properties"]


def test_tool_input_schema_falls_back_to_camel_case():
    tool = SimpleNamespace(
        inputSchema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    )
    schema = tool_input_schema(tool)
    assert schema["required"] == ["q"]


def test_tool_metadata_from_mcp_tool():
    tool = SimpleNamespace(
        name="get_time",
        description="Current time",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    meta = tool_metadata_from_mcp_tool(tool)
    assert meta["docstring"] == "Current time"
    assert meta["all_params"] == []
    assert "module" not in meta


def test_tool_metadata_from_mcp_tool_reads_module_meta():
    tool = SimpleNamespace(
        name="detect_fire_tool",
        description="Detect fires",
        input_schema={"type": "object", "properties": {}},
        meta={"module": "hazards", "module_version": "1.0.0"},
    )
    meta = tool_metadata_from_mcp_tool(tool)
    assert meta["module"] == "hazards"


def test_tool_metadata_from_mcp_tool_reads_meta_alias():
    tool = SimpleNamespace(
        name="query_stac_catalog",
        description="STAC",
        input_schema={"type": "object", "properties": {}},
        _meta={"module": "imagery"},
    )
    meta = tool_metadata_from_mcp_tool(tool)
    assert meta["module"] == "imagery"


def test_extract_tool_payload_from_structured_content():
    result = SimpleNamespace(
        structured_content={"tool_name": "get_time", "message": "ok", "error": False},
        content=[],
    )
    payload = extract_tool_payload("get_time", result)
    assert payload["message"] == "ok"


def test_extract_tool_payload_from_text_content():
    result = SimpleNamespace(
        structured_content=None,
        content=[SimpleNamespace(text='{"tool_name":"get_time","message":"12h00","error":false}')],
    )
    payload = extract_tool_payload("get_time", result)
    assert payload["message"] == "12h00"
