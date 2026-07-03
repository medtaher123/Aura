"""Document QA domain node."""

from __future__ import annotations

from eo_llm.graph.nodes.domain_base import DomainNode
from eo_llm.graph.nodes.helpers import wrap_domain_result
from eo_llm.graph.state import GraphState, GraphStateModel




class DocumentQADomainNode(DomainNode):
    """Answer questions grounded in an uploaded document."""

    @property
    def domain_name(self) -> str:
        return "document_qa"

    def execute(self, s: GraphStateModel) -> GraphState:
        if not isinstance(s.document_ref, dict) or not s.document_ref:
            return wrap_domain_result(
                self.domain_name,
                {
                    "status": "skipped",
                    "message": "No uploaded document available.",
                    "error": True,
                },
            )

        try:
            out = self._adapter.answer_question_with_document(
                query=s.user_query or s.query,
                document_ref=dict(s.document_ref),
            )
            answer = str(out.get("answer") or "").strip()
            citations = (
                out.get("citations") if isinstance(out.get("citations"), list) else []
            )
            return wrap_domain_result(
                self.domain_name,
                {
                    "status": "done" if answer else "error",
                    "result": {"answer": answer, "citations": citations},
                    "summary": {"successful_steps": 1 if answer else 0},
                    "message": "" if answer else "Document QA returned empty answer.",
                    "error": not bool(answer),
                },
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return wrap_domain_result(
                self.domain_name,
                {
                    "status": "error",
                    "message": f"Document QA failed: {exc}",
                    "error": True,
                },
            )

document_qa_node = DocumentQADomainNode()
