"""Finalizer node: builds final answer text via Bedrock streaming."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from eo_llm.adapters.mcp_client import emit_stream_event
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, dump_state, GraphStateModel
from eo_llm.prompts import get_finalizer_prompt

logger = logging.getLogger("eo_llm.finalizer")


def _fallback_answer(user_q: str, exc: Exception) -> str:
    """User-facing message when Bedrock final-answer composition fails."""
    detail = str(exc).strip() or type(exc).__name__
    prefix = f"I wasn't able to produce an answer for: {user_q}." if user_q else "I wasn't able to produce an answer."
    return f"{prefix} The reasoning service returned an error: {detail}"


class FinalizerNode(GraphNode):
    node_name = "finalizer"
    status_stage = "analyzing"
    status_message = "Composing the final answer..."

    def run(self, s: GraphStateModel) -> GraphState:
        # A direct answer was already produced upstream (e.g. orchestrator handling
        # empty input or tools_info). Preserve it verbatim instead of re-composing.
        if s.next_step == "finalize_direct" and s.final_answer.strip():
            emit_stream_event({"type": "token", "content": s.final_answer})
            return dump_state(s)

        source = s.answer_source or "domain_tools"
        evidence = s.aggregated_evidence or "No evidence."
        query = s.query

        try:
            s.final_answer = self._stream_final_answer(
                query=query,
                answer_source=source,
                aggregated_evidence=evidence,
                domain_results=dict(s.domain_results),
                web_results=list(s.web_results),
            )
        except (RuntimeError, ValueError) as exc:
            logger.warning(
                "final answer streaming failed (%s: %s)",
                type(exc).__name__,
                str(exc)[:300],
            )
            user_q = (s.user_query or "").strip() or (s.query or "").strip()
            s.final_answer = _fallback_answer(user_q, exc)
            emit_stream_event({"type": "token", "content": s.final_answer})
        return dump_state(s)

    def _stream_final_answer(
        self,
        *,
        query: str,
        answer_source: str,
        aggregated_evidence: str,
        domain_results: dict,
        web_results: list,
    ) -> str:
        adapter = self._adapter
        model_id = adapter.finalizer_model_id
        if not adapter.is_ready() or not model_id:
            raise RuntimeError("Bedrock finalizer unavailable.")

        provider = adapter.provider
        assert provider is not None

        today_utc = datetime.now(timezone.utc).date().isoformat()
        system_prompt, user_prompt = get_finalizer_prompt(
            today_utc=today_utc,
            query=query,
            answer_source=answer_source,
            aggregated_evidence=aggregated_evidence,
            domain_results_json=json.dumps(domain_results, default=str)[:6000],
            web_results_json=json.dumps(web_results, default=str)[:2500],
        )

        parts: list[str] = []
        for chunk in provider.call_stream(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=900,
        ):
            if not chunk:
                continue
            parts.append(chunk)
            emit_stream_event({"type": "token", "content": chunk})

        final_answer = "".join(parts).strip()
        if not final_answer:
            raise RuntimeError("Bedrock finalizer returned empty answer.")
        return final_answer


finalizer_node = FinalizerNode()
