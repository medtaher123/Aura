"""Document QA domain node."""

from __future__ import annotations

from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter
from eo_llm.graph.state import GraphState, validate_state


def document_qa_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    selected = set(s.selected_domains)
    if "document_qa" not in selected:
        return {}
    if not isinstance(s.document_ref, dict) or not s.document_ref:
        return {
            "domain_results": {
                "document_qa": {
                    "status": "skipped",
                    "message": "No uploaded document available.",
                    "error": True,
                }
            }
        }
    try:
        out = AgentCoreAdapter().answer_question_with_document(
            query=s.user_query or s.query,
            document_ref=dict(s.document_ref),
        )
        answer = str(out.get("answer") or "").strip()
        citations = out.get("citations") if isinstance(out.get("citations"), list) else []
        return {
            "domain_results": {
                "document_qa": {
                    "status": "done" if answer else "error",
                    "result": {"answer": answer, "citations": citations},
                    "summary": {"successful_steps": 1 if answer else 0},
                    "message": "" if answer else "Document QA returned empty answer.",
                    "error": not bool(answer),
                }
            }
        }
    except (RuntimeError, ValueError, OSError) as exc:
        return {
            "domain_results": {
                "document_qa": {
                    "status": "error",
                    "message": f"Document QA failed: {exc}",
                    "error": True,
                }
            }
        }
