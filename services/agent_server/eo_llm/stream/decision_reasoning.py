"""Emit and format user-facing reasoning for agent decisions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from eo_llm.adapters.mcp_client import emit_stream_event

DecisionFormatter = Callable[[str, dict[str, Any]], str]

_FORMATTERS: dict[str, DecisionFormatter] = {}
_STAGE_BY_SOURCE: dict[str, str] = {
    "route_domains": "planning",
    "route_keyword_fallback": "planning",
    "tool_plan": "tool_call",
}


def register_formatter(
    source: str,
    formatter: DecisionFormatter,
    *,
    stage: str | None = None,
) -> None:
    """Register a display formatter for a decision source (open for extension)."""
    _FORMATTERS[source] = formatter
    if stage is not None:
        _STAGE_BY_SOURCE[source] = stage


def stage_for_source(source: str) -> str:
    return _STAGE_BY_SOURCE.get(source, "planning")


def format_decision_reasoning(event: dict[str, Any]) -> str:
    """Turn a thinking stream event into a user-facing line."""
    source = str(event.get("source") or "").strip()
    reasoning = str(event.get("reasoning") or "").strip()
    if not reasoning:
        return ""

    context = {
        key: value
        for key, value in event.items()
        if key not in {"type", "source", "reasoning"}
    }
    formatter = _FORMATTERS.get(source)
    if formatter is not None:
        return formatter(reasoning, context).strip()

    label = source.replace("_", " ").strip().title() or "Decision"
    return f"{label}: {reasoning}"


def emit_decision_reasoning(source: str, reasoning: str, **context: Any) -> None:
    """Emit a thinking event when non-empty reasoning is available."""
    text = (reasoning or "").strip()
    if not text:
        return
    emit_stream_event(
        {
            "type": "thinking",
            "source": source,
            "reasoning": text,
            **context,
        }
    )


def thinking_payload_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Build websocket thinking payload from an internal stream event."""
    source = str(event.get("source") or "").strip()
    reasoning = str(event.get("reasoning") or "").strip()
    content = format_decision_reasoning(event)
    if not source or not content:
        return None
    return {
        "source": source,
        "content": content,
        "reasoning": reasoning,
        "stage": stage_for_source(source),
    }


def _to_agent_action_voice(reasoning: str) -> str:
    """Normalize imperative tool-plan phrasing into first-person agent voice."""
    text = (reasoning or "").strip()
    if not text:
        return ""

    lower = text.lower()
    if lower.startswith(("i ", "i'm ", "i'll ", "i have", "i need", "i should", "i will")):
        return text

    first_word = lower.split(maxsplit=1)[0] if lower.split() else ""
    imperative_starts = {
        "retrieve",
        "fetch",
        "query",
        "search",
        "get",
        "call",
        "check",
        "analyze",
        "load",
        "use",
        "start",
        "run",
        "open",
    }
    if first_word in imperative_starts:
        return f"I have to {text[0].lower()}{text[1:]}"
    return text


def _format_route_domains(reasoning: str, context: dict[str, Any]) -> str:
    return (reasoning or "").strip()


def _format_tool_plan(reasoning: str, context: dict[str, Any]) -> str:
    return _to_agent_action_voice(reasoning)


register_formatter("route_domains", _format_route_domains, stage="planning")
register_formatter("route_keyword_fallback", _format_route_domains, stage="planning")
register_formatter("tool_plan", _format_tool_plan, stage="tool_call")
