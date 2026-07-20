"""Web search fallback node.

Uses the lightweight search backend (Tavily/Brave/DuckDuckGo) by default, and
the heavyweight AgentCore Browser (Strands) only when it is explicitly enabled
via ``AGENTCORE_BROWSER_ENABLED=true``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from eo_llm.adapters.agentcore_browser import run_browser_research
from eo_llm.adapters.web_search import run_web_search
from eo_llm.config import get_config
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, GraphStateModel


def _domain_result_as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        return dump(mode="python")
    return {}


def _domain_failure_hint(domain_results: dict[str, Any]) -> str:
    lines: list[str] = []
    for name, raw in domain_results.items():
        raw = _domain_result_as_dict(raw)
        if not raw:
            continue
        status = raw.get("status")
        msg = raw.get("message")
        summary = raw.get("summary")
        err = raw.get("error")
        piece = f"{name}: status={status!r}"
        if msg:
            piece += f" message={str(msg)[:400]}"
        if isinstance(summary, dict):
            piece += f" successful_steps={summary.get('successful_steps')!r}"
        if err is not None:
            piece += f" error={err!r}"
        lines.append(piece)
    return "\n".join(lines)[:4000]



#TODO: is this node useful? (mtbh)
class WebSearchNode(GraphNode):
    node_name = "web_search"
    status_stage = "web_search"
    status_message = "Searching the web..."

    async def run(self, s: GraphStateModel) -> GraphState:
        contextualized = s.query.strip()
        user_q = (s.user_query or "").strip() or contextualized
        hint = _domain_failure_hint(dict(s.domain_results))

        if bool(getattr(get_config(), "agentcore_browser_enabled", False)):
            web_results = await asyncio.to_thread(
                run_browser_research,
                contextualized_query=contextualized,
                user_query=user_q,
                domain_failure_hint=hint,
            )
        else:
            web_results = await asyncio.to_thread(
                run_web_search,
                contextualized_query=contextualized,
                user_query=user_q,
                domain_failure_hint=hint,
            )
        return {"web_results": web_results}


web_search_node = WebSearchNode()
