"""Document QA domain node."""

from __future__ import annotations
from typing import Any

from eo_llm.adapters.bedrock.llm_model_router import LLMModelRouter
from eo_llm.document_store import load_document_bytes
from eo_llm.graph.nodes.domain_base import DomainNode
from eo_llm.graph.nodes.helpers import wrap_domain_result
from eo_llm.graph.state import GraphState, GraphStateModel
from eo_llm.prompts import DOCUMENT_QA_SYSTEM


class DocumentQADomainNode(DomainNode):
    """Answer questions grounded in an uploaded document."""

    domain_name = "document_qa"
    status_message = "Reading the document..."

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
            out = self.answer_question_with_document(
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


    def extract_text_from_converse_response(self, response: dict[str, Any]) -> str:
        content = response.get("output", {}).get("message", {}).get("content", [])
        if not isinstance(content, list):
            return ""
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
            citations_block = part.get("citationsContent")
            if isinstance(citations_block, dict):
                generated = citations_block.get("content")
                if isinstance(generated, list):
                    for item in generated:
                        if isinstance(item, dict):
                            t = item.get("text")
                            if isinstance(t, str) and t.strip():
                                text_parts.append(t.strip())
        return "\n".join(text_parts).strip()


    def extract_document_citations(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        content = response.get("output", {}).get("message", {}).get("content", [])
        if not isinstance(content, list):
            return []
        citations: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            citations_block = part.get("citationsContent")
            if not isinstance(citations_block, dict):
                continue
            refs = citations_block.get("citations")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, dict):
                    citations.append(ref)
        return citations

                
    def answer_question_with_document(
        self, *, query: str, document_ref: dict[str, Any]
    ) -> dict[str, Any]:
        """Answer a user question grounded in one uploaded document."""
        
        doc_bytes = load_document_bytes(document_ref)
        if not doc_bytes:
            raise ValueError("Uploaded document is empty.")

        neutral_name = str(document_ref.get("neutral_name") or "Uploaded Document").strip()
        format_value = str(document_ref.get("format") or "pdf").strip().lower() or "pdf"
        user_prompt = (query or "").strip() or "Summarize this document."

        response = LLMModelRouter().call_standard_with_document(
            system_prompt=DOCUMENT_QA_SYSTEM,
            user_prompt=user_prompt,
            document_bytes=doc_bytes,
            document_name=neutral_name,
            document_format=format_value,
        )

        return {
            "answer": self.extract_text_from_converse_response(response),
            "citations": self.extract_document_citations(response),
        }


document_qa_node = DocumentQADomainNode()
