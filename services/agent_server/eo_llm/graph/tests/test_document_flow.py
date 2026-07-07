"""Document upload flow coverage for orchestrator and domain node."""

from __future__ import annotations

from types import SimpleNamespace

from eo_llm.adapters.bedrock_llm_adapter import BedrockLLMAdapter
from eo_llm.graph.nodes.domains.document_qa_node import document_qa_node
from eo_llm.graph.nodes.orchestrator_node import orchestrator_node


def test_orchestrator_resolves_location_from_document(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_extract(_self, *, query: str, document_ref: dict[str, str]) -> str:
        assert "location in the document" in query.lower()
        assert document_ref["document_id"] == "doc-1"
        return "Paris, France"

    def fake_route(_self, *, query: str):
        seen["query"] = query
        return SimpleNamespace(domains=["disaster_detection"], confidence=0.9)

    monkeypatch.setattr(BedrockLLMAdapter, "extract_location_from_document", fake_extract)
    monkeypatch.setattr(BedrockLLMAdapter, "route_domains", fake_route)

    out = orchestrator_node(
        {
            "query": "what's the number of events in the location in the document",
            "user_query": "what's the number of events in the location in the document",
            "document_ref": {"document_id": "doc-1"},
        }
    )
    assert out.get("place_hint") == "Paris, France"
    assert "Implicit location context: Paris, France" in seen["query"]
    assert "disaster_detection" in out.get("selected_domains", [])
    assert "document_qa" in out.get("selected_domains", [])


def test_document_qa_node_uses_uploaded_document(monkeypatch) -> None:
    def fake_answer(_self, *, query: str, document_ref: dict[str, str]):
        assert "fires in paris" in query.lower()
        assert document_ref["document_id"] == "doc-2"
        return {"answer": "The document reports 12 events.", "citations": []}

    monkeypatch.setattr(BedrockLLMAdapter, "answer_question_with_document", fake_answer)

    out = document_qa_node(
        {
            "query": "How many fire events in the document?",
            "user_query": "How many fire events in the document about fires in Paris?",
            "selected_domains": ["document_qa"],
            "document_ref": {"document_id": "doc-2", "path": "/tmp/x.pdf", "format": "pdf"},
        }
    )
    result = out["domain_results"]["document_qa"]
    assert result["status"] == "done"
    assert "12 events" in result["result"]["answer"]
