"""Web search tool for MCP Server.

Uses the best available provider:
1. Tavily   - if ``TAVILY_API_KEY`` is set
2. Brave    - if ``BRAVE_API_KEY`` is set
3. DuckDuckGo - keyless fallback (requires the ``ddgs`` package)
"""

from __future__ import annotations

import os

import httpx

from mcp_singleton import mcp
from utils.contracts import ToolResponse

_DEFAULT_MAX_RESULTS = 6
_HTTP_TIMEOUT_S = 15.0
_TOOL_NAME = "web_search_tool"


def _clip(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _search_tavily(query: str, api_key: str, max_results: int) -> list[dict[str, str]]:
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": True,
        },
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    rows: list[dict[str, str]] = []
    answer = str(data.get("answer") or "").strip()
    if answer:
        rows.append({"title": "Web answer", "snippet": _clip(answer), "url": ""})
    for item in data.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "title": str(item.get("title") or "").strip() or "Result",
                "snippet": _clip(str(item.get("content") or "")),
                "url": str(item.get("url") or "").strip(),
            }
        )
    return rows


def _search_brave(query: str, api_key: str, max_results: int) -> list[dict[str, str]]:
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    results = (data.get("web", {}) or {}).get("results", []) or []
    rows: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "title": str(item.get("title") or "").strip() or "Result",
                "snippet": _clip(str(item.get("description") or "")),
                "url": str(item.get("url") or "").strip(),
            }
        )
    return rows


def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS  # type: ignore[import-untyped]
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Keyless web search needs the 'ddgs' package "
                "(pip install ddgs), or set TAVILY_API_KEY / BRAVE_API_KEY."
            ) from exc

    rows: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results) or []:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "title": str(item.get("title") or "").strip() or "Result",
                    "snippet": _clip(str(item.get("body") or "")),
                    "url": str(item.get("href") or item.get("url") or "").strip(),
                }
            )
    return rows


def _run_search(query: str, max_results: int) -> tuple[str, list[dict[str, str]]]:
    tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    brave_key = (os.getenv("BRAVE_API_KEY") or "").strip()

    if tavily_key:
        return "Tavily", _search_tavily(query, tavily_key, max_results)
    if brave_key:
        return "Brave", _search_brave(query, brave_key, max_results)
    return "DuckDuckGo", _search_duckduckgo(query, max_results)


def _format_message(query: str, provider: str, rows: list[dict[str, str]]) -> str:
    lines = [f"Web search results for '{query}' via {provider}:"]
    for idx, row in enumerate(rows, start=1):
        title = row.get("title") or "Result"
        snippet = row.get("snippet") or ""
        url = row.get("url") or ""
        line = f"{idx}. {title}"
        if snippet:
            line += f" — {snippet}"
        if url:
            line += f" ({url})"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool()
def web_search_tool(
    query: str,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> ToolResponse:
    """Search the public web for recent news, context, or facts not covered by EO tools.

    Prefer domain-specific earth-observation tools first. Use this tool to
    corroborate results, fill gaps, or answer questions that need open-web sources.

    Args:
        query: Search query string
        max_results: Maximum number of result rows to return (default 6)
    """
    cleaned = (query or "").strip()
    if not cleaned:
        return ToolResponse(
            tool_name=_TOOL_NAME,
            message="No search query was provided.",
            data={"results": []},
            error=True,
        )

    try:
        capped = max(1, min(int(max_results), 10))
    except (TypeError, ValueError):
        capped = _DEFAULT_MAX_RESULTS

    try:
        provider, rows = _run_search(cleaned, capped)
    except Exception as exc:
        return ToolResponse(
            tool_name=_TOOL_NAME,
            message=f"Web search failed: {str(exc)[:500]}",
            data={"query": cleaned, "results": []},
            error=True,
        )

    rows = [r for r in rows if r.get("snippet") or r.get("url")]
    if not rows:
        return ToolResponse(
            tool_name=_TOOL_NAME,
            message=f"{provider} returned no results for: {cleaned}",
            data={"query": cleaned, "provider": provider.lower(), "results": []},
            error=True,
        )

    return ToolResponse(
        tool_name=_TOOL_NAME,
        message=_format_message(cleaned, provider, rows),
        data={
            "query": cleaned,
            "provider": provider.lower(),
            "results": rows,
        },
        error=False,
    )
