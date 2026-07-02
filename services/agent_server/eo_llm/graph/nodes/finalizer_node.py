"""Finalizer node: builds final answer text."""

from __future__ import annotations

import logging

from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter
from eo_llm.graph.state import GraphState, dump_state, validate_state

logger = logging.getLogger("eo_llm.finalizer")


def _fallback_answer(user_q: str, exc: Exception) -> str:
    """User-facing message when Bedrock final-answer composition fails."""
    detail = str(exc).strip() or type(exc).__name__
    prefix = f"I wasn't able to produce an answer for: {user_q}." if user_q else "I wasn't able to produce an answer."
    return f"{prefix} The reasoning service returned an error: {detail}"


def finalizer_node(state: GraphState) -> GraphState:
    s = validate_state(state)

    # A direct answer was already produced upstream (e.g. orchestrator handling
    # empty input or tools_info). Preserve it verbatim instead of re-composing.
    if s.next_step == "finalize_direct" and s.final_answer.strip():
        return dump_state(s)

    source = s.answer_source or "domain_tools"
    evidence = s.aggregated_evidence or "No evidence."
    query = s.query

    try:
        s.final_answer = AgentCoreAdapter().compose_final_answer(
            query=query,
            answer_source=source,
            aggregated_evidence=evidence,
            domain_results=dict(s.domain_results),
            web_results=list(s.web_results),
        )
    except (RuntimeError, ValueError) as exc:
        logger.warning(
            "compose_final_answer failed (%s: %s)",
            type(exc).__name__,
            str(exc)[:300],
        )
        user_q = (s.user_query or "").strip() or (s.query or "").strip()
        s.final_answer = _fallback_answer(user_q, exc)
    return dump_state(s)

