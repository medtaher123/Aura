"""Lightweight web search for the graph's web-fallback node.

This is the default web backend used when the heavyweight AgentCore Browser
(Strands) is not enabled. It selects a provider automatically:

1. Tavily   - if ``TAVILY_API_KEY`` is set (agent-friendly search API)
2. Brave    - if ``BRAVE_API_KEY`` is set
3. DuckDuckGo - keyless fallback (requires the ``ddgs`` package)

All providers return rows in the GraphState ``web_results`` shape:
``{"title": str, "snippet": str, "url": str}``. Any failure degrades to a
single guidance row rather than raising, so the graph keeps running.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_DEFAULT_MAX_RESULTS = 6
_HTTP_TIMEOUT_S = 15.0


def _clip(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _guidance_row(message: str) -> list[dict[str, str]]:
    return [{"title": "Web search unavailable", "snippet": message, "url": ""}]


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


def run_web_search(
    *,
    contextualized_query: str,
    user_query: str,
    domain_failure_hint: str = "",
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> list[dict[str, str]]:
    """Run a web search with the best available provider; never raises."""
    query = (user_query or contextualized_query or "").strip()
    if not query:
        return _guidance_row("No query was provided for web search.")

    tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    brave_key = (os.getenv("BRAVE_API_KEY") or "").strip()

    if tavily_key:
        provider, runner = "Tavily", lambda: _search_tavily(query, tavily_key, max_results)
    elif brave_key:
        provider, runner = "Brave", lambda: _search_brave(query, brave_key, max_results)
    else:
        provider, runner = "DuckDuckGo", lambda: _search_duckduckgo(query, max_results)

    try:
        rows = runner()
    except Exception as exc:  # pragma: no cover - network/provider dependent
        return _guidance_row(f"{provider} web search failed: {str(exc)[:500]}")

    rows = [r for r in rows if r.get("snippet") or r.get("url")]
    if not rows:
        return _guidance_row(f"{provider} returned no results for: {query}")
    return rows


def web_search_runtime_info() -> dict[str, Any]:
    """Non-secret diagnostics about the lightweight web search backend."""
    has_tavily = bool((os.getenv("TAVILY_API_KEY") or "").strip())
    has_brave = bool((os.getenv("BRAVE_API_KEY") or "").strip())
    ddg_ok = False
    try:
        import importlib

        try:
            importlib.import_module("ddgs")
            ddg_ok = True
        except ImportError:
            importlib.import_module("duckduckgo_search")
            ddg_ok = True
    except ImportError:
        ddg_ok = False
    if has_tavily:
        active = "tavily"
    elif has_brave:
        active = "brave"
    elif ddg_ok:
        active = "duckduckgo"
    else:
        active = "none"
    return {
        "web_search_provider": active,
        "web_search_tavily_key_set": has_tavily,
        "web_search_brave_key_set": has_brave,
        "web_search_duckduckgo_importable": ddg_ok,
    }

