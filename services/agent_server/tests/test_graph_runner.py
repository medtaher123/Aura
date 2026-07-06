"""Unit tests for graph runner DTOs, artifact merging, and response factory."""

from eo_llm.graph.state import GraphStateModel

from src.services.graph_runner.artifacts import ArtifactAggregator, PydeckMerger
from src.services.graph_runner.models import ArtifactBundle, ChatMessage, GraphTurnRequest
from src.services.graph_runner.responses import ToolResponseFactory


def test_graph_turn_request_contextualizes_query():
    request = GraphTurnRequest(
        english_query="Show fires there",
        user_id="u1",
        session_id="s1",
        chat_history=[
            ChatMessage(role="user", content="What about Berlin?"),
            ChatMessage(role="assistant", content="Berlin is in Germany."),
        ],
    )
    contextualized = request.contextualize_query()
    assert "Current user message: Show fires there" in contextualized
    assert "BERLIN" in contextualized.upper()


def test_pydeck_merger_combines_multiple_specs():
    spec_a = {
        "title": "Fires",
        "layers": [{"type": "HeatmapLayer", "data": [{"lat": 1, "lon": 2}]}],
    }
    spec_b = {
        "title": "Events",
        "points": [{"lat": 3, "lon": 4}],
        "radius": 100,
    }
    merged = PydeckMerger().merge([spec_a, spec_b])
    assert merged["title"] == "Fires + Events"
    assert len(merged["layers"]) == 2
    assert merged["layers"][1]["type"] == "ScatterplotLayer"
    assert "points" not in merged


def test_artifact_aggregator_deduplicates_urls_and_merges_pydeck():
    bundles = [
        ArtifactBundle(
            maps=["legacy.html", {"layers": [{"type": "A"}], "title": "A"}],
            thumbnails=["t1", "t1"],
            urls=["https://a", "https://b"],
        ),
        ArtifactBundle(
            maps=[{"layers": [{"type": "B"}], "title": "B"}],
            urls=["https://b", "https://c"],
        ),
    ]
    result = ArtifactAggregator().aggregate(bundles, extra_urls=["https://c", ""])
    assert result.maps[0] == "legacy.html"
    assert len(result.maps) == 2
    combined = result.maps[1]
    assert combined["title"] == "A + B"
    assert len(combined["layers"]) == 2
    assert result.thumbnails == ["t1"]
    assert result.urls == ["https://a", "https://b", "https://c"]


def test_tool_response_factory_paused_state():
    state = GraphStateModel(
        stopped_for_location_confirmation=True,
        location_candidates=[{"display_name": "Berlin", "lat": 52.5, "lon": 13.4}],
    )
    response = ToolResponseFactory.from_paused_state(state)
    assert response.data["needs_location_confirmation"] is True
    assert len(response.data["candidates"]) == 1
    assert "pause" in response.data


def test_tool_response_factory_completed_state_with_location():
    state = GraphStateModel(
        final_answer="Done.",
        answer_source="domain_tools",
        selected_domains=["fire_detection"],
        resolved_location={"display_name": "Berlin", "lat": 52.5, "lon": 13.4},
    )
    response = ToolResponseFactory().from_completed_state(state)
    assert response.message == "Done."
    assert response.error is False
    assert response.city == "Berlin"
    assert response.coordinates == {"lat": 52.5, "lon": 13.4}
