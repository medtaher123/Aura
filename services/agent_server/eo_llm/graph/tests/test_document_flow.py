"""Document upload flow coverage for orchestrator and domain node."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from eo_llm.graph.nodes.domains.document_qa_node import DocumentQADomainNode, document_qa_node
from eo_llm.graph.nodes.orchestrator_node import OrchestratorNode, orchestrator_node


def test_orchestrator_resolves_location_from_document(monkeypatch) -> None:
    seen: dict[str, str] = {}

    async def fake_extract(_self, *, query: str, document_ref: dict[str, str]) -> str:
        assert "location in the document" in query.lower()
        assert document_ref["document_id"] == "doc-1"
        return "Paris, France"

    async def fake_route(_self, *, place_hint: str | None = None):
        seen["place_hint"] = place_hint or ""
        return SimpleNamespace(domains=["disaster_detection"], confidence=0.9)

    monkeypatch.setattr(OrchestratorNode, "_extract_location_from_document", fake_extract)
    monkeypatch.setattr(OrchestratorNode, "route_domains", fake_route)

    out = asyncio.run(
        orchestrator_node(
            {
                "query": "what's the number of events in the location in the document",
                "user_query": "what's the number of events in the location in the document",
                "document_ref": {"document_id": "doc-1"},
            }
        )
    )
    assert out.get("place_hint") == "Paris, France"
    assert seen["place_hint"] == "Paris, France"
    assert "Implicit location" not in (out.get("query") or "")
    assert "disaster_detection" in out.get("selected_domains", [])
    assert "document_qa" in out.get("selected_domains", [])


def test_document_qa_node_uses_uploaded_document(monkeypatch) -> None:
    async def fake_answer(_self, *, query: str, document_ref: dict[str, str]):
        assert "fires in paris" in query.lower()
        assert document_ref["document_id"] == "doc-2"
        return {"answer": "The document reports 12 events.", "citations": []}

    monkeypatch.setattr(DocumentQADomainNode, "answer_question_with_document", fake_answer)

    out = asyncio.run(
        document_qa_node(
            {
                "query": "How many fire events in the document?",
                "user_query": "How many fire events in the document about fires in Paris?",
                "selected_domains": ["document_qa"],
                "document_ref": {"document_id": "doc-2", "path": "/tmp/x.pdf", "format": "pdf"},
            }
        )
    )
    result = out["domain_results"]["document_qa"]
    assert result["status"] == "done"
    assert "12 events" in result["result"]["answer"]
