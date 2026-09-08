"""Shared MCP Streamable HTTP transport helpers (MCP SDK v2)."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from src.config import get_config


def mcp_streamable_http_url(
    base_url: str | None = None,
    *,
    append_mcp_path: bool = True,
) -> str:
    """Normalize configured MCP base URL to the Streamable HTTP endpoint.

    Most servers expose MCP at ``{base}/mcp``. Pass ``append_mcp_path=False``
    when ``base_url`` is already the complete endpoint (e.g. Pappers
    ``https://mcp.pappers.fr/{api_key}``).
    """
    if base_url is None:
        try:
            base_url = get_config().mcp_server_url.strip()
        except Exception:
            base_url = ""
    if not base_url:
        base_url = (os.getenv("MCP_SERVER_URL") or "http://localhost:8000").strip()

    base = base_url.rstrip("/")
    if not append_mcp_path or base.endswith("/mcp"):
        return base
    return f"{base}/mcp"


def tool_input_schema(tool: Any) -> dict[str, Any]:
    """Read a tool's JSON Schema under MCP SDK v1 (inputSchema) or v2 (input_schema)."""
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    if isinstance(schema, dict):
        return schema
    # Pydantic model dump fallback
    dump = getattr(tool, "model_dump", None)
    if callable(dump):
        data = dump()
        if isinstance(data, dict):
            for key in ("input_schema", "inputSchema"):
                value = data.get(key)
                if isinstance(value, dict):
                    return value
    return {}


def tool_meta_dict(tool: Any) -> dict[str, Any]:
    """Read MCP tool ``meta`` / ``_meta`` from an SDK object or plain namespace."""
    for attr in ("meta", "_meta"):
        value = getattr(tool, attr, None)
        if isinstance(value, dict):
            return value
    dump = getattr(tool, "model_dump", None)
    if callable(dump):
        data = dump(by_alias=True)
        if isinstance(data, dict):
            for key in ("_meta", "meta"):
                nested = data.get(key)
                if isinstance(nested, dict):
                    return nested
    return {}


def tool_module_from_mcp_tool(tool: Any) -> str | None:
    """Extract Metaplanet module name from MCP tool metadata, if present."""
    meta = tool_meta_dict(tool)
    module = meta.get("module")
    if isinstance(module, str) and module.strip():
        return module.strip()
    nested = meta.get("metaplanet")
    if isinstance(nested, dict):
        module = nested.get("module")
        if isinstance(module, str) and module.strip():
            return module.strip()
    return None


def tool_metadata_from_mcp_tool(tool: Any) -> dict[str, Any]:
    """Normalize list_tools entries into planner-friendly metadata."""
    schema = tool_input_schema(tool)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    out: dict[str, Any] = {
        "all_params": [str(k) for k in properties.keys()] if isinstance(properties, dict) else [],
        "required_params": [str(k) for k in required] if isinstance(required, list) else [],
        "docstring": str(getattr(tool, "description", "") or ""),
        "input_schema": schema,
    }
    module = tool_module_from_mcp_tool(tool)
    if module is not None:
        out["module"] = module
    return out


def extract_tool_payload(tool_name: str, result: Any) -> Any:
    """Pull JSON tool payload from an MCP CallToolResult (text and/or structured)."""
    # Prefer structured content when the server emitted it (MCP SDK v2).
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        structured.setdefault("tool_name", tool_name)
        return structured

    content = getattr(result, "content", None) or []
    if not content:
        is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
        return {
            "tool_name": tool_name,
            "message": "Empty MCP result.",
            "data": {},
            "error": is_error or True,
        }

    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return {
            "tool_name": tool_name,
            "message": "MCP returned non-text content.",
            "data": {"raw": str(result)},
            "error": False,
        }

    try:
        parsed = json.loads(text)
    except Exception:
        return {
            "tool_name": tool_name,
            "message": str(text),
            "data": {},
            "error": False,
        }

    if isinstance(parsed, dict):
        parsed.setdefault("tool_name", tool_name)
        return parsed
    return {
        "tool_name": tool_name,
        "message": str(parsed),
        "data": {},
        "error": False,
    }
