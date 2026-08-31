"""Unit tests for graph runner DTOs, artifact merging, and turn-result factory."""

from uuid import uuid4

from eo_llm.adapters.bedrock.llm_provider import ConverseResponse, LLMProvider
from eo_llm.graph.state import GraphStateModel

from src.db.models.message import AssistantMessage, UserMessage
from src.services.graph_runner.artifacts import ArtifactAggregator, PydeckMerger
from src.services.graph_runner.models import ArtifactBundle, GraphTurnRequest, GraphTurnResult
from src.services.graph_runner.responses import GraphTurnResultFactory


def test_graph_turn_request_keeps_message_history_out_of_query():
    request = GraphTurnRequest(
        thread_id="session:turn",
        message=UserMessage.create("Show fires there"),
        user_id="u1",
        session_id="s1",
        chat_history=[
            UserMessage.create("What about Berlin?"),
            AssistantMessage.create("Berlin is in Germany."),
        ],
    )
    state = request.to_graph_input()
    assert state["query"] == "Show fires there"
    assert "Berlin" not in state["query"]
    assert len(request.chat_history) == 2
    assert request.chat_history[0].content == "What about Berlin?"
    assert request.llm_chat_history()[-1] is request.message
    assert len(request.llm_chat_history()) == 3


def test_llm_provider_formats_message_history():
    class _Stub(LLMProvider):
        @property
        def name(self) -> str:
            return "stub"

        @property
        def last_failure_reason(self) -> str:
            return ""

        async def call_structured(self, **kwargs):
            return None

        async def call_stream(self, **kwargs):
            if False:
                yield ""

        async def call_standard_with_document(self, **kwargs):
            return {}

        async def call_converse(self, **kwargs):
            return ConverseResponse(stop_reason="end_turn", text="ok")

    formatted = _Stub().format_messages(
        [
            UserMessage.create("What about Berlin?"),
            AssistantMessage.create("Berlin is in Germany."),
            UserMessage.create("Show fires there"),
        ],
    )
    assert formatted[0]["role"] == "user"
    assert "Berlin?" in formatted[0]["content"][0]["text"]
    assert formatted[1]["role"] == "assistant"
    assert formatted[2]["role"] == "user"
    assert formatted[2]["content"][0]["text"] == "Show fires there"

    from src.db.models.message_attachments import FileAttachment, LocationAttachment

    turn = UserMessage.create(
        "Show fires",
        attachments=[
            LocationAttachment(name="Tunis, Tunisia", coordinates=[36.8, 10.1]),
        ],
    )
    preferred = _Stub().format_messages([turn])
    assert preferred[0]["role"] == "user"
    assert preferred[0]["content"][0]["text"] == "Show fires"
    assert preferred[0]["content"][1]["text"] == turn.attachments[0].llm_text()
    assert "Tunis" in preferred[0]["content"][1]["text"]
    assert "Query:" not in preferred[0]["content"][0]["text"]

    file_att = FileAttachment(file_id=uuid4(), name="report.pdf")
    file_only = UserMessage.create("", attachments=[file_att])
    assert file_only.has_content
    assert _Stub().format_file_attachment(file_att) == [
        {"text": file_att.llm_text()}
    ]
    formatted_file = _Stub().format_messages([file_only])
    assert formatted_file[0]["content"][0]["text"] == file_att.llm_text()


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
            maps=[{"layers": [{"type": "A"}], "title": "A"}],
            thumbnails=["t1", "t1"],
            urls=["https://a", "https://b"],
        ),
        ArtifactBundle(
            maps=[{"layers": [{"type": "B"}], "title": "B"}],
            urls=["https://b", "https://c"],
        ),
    ]
    result = ArtifactAggregator().aggregate(bundles, extra_urls=["https://c", ""])
    assert len(result.maps) == 1
    combined = result.maps[0]
    assert combined["title"] == "A + B"
    assert len(combined["layers"]) == 2
    assert result.thumbnails == ["t1"]
    assert result.urls == ["https://a", "https://b", "https://c"]


def test_graph_turn_result_factory_from_interrupt():
    payload = {
        "data": {
            "needs_input": {
                "location": {
                    "candidates": [
                        {"display_name": "Berlin", "lat": 52.5, "lon": 13.4},
                    ],
                    "prompt": "Several places match your query. Please choose a location.",
                }
            }
        },
        "prompt": "Pick a location",
    }
    result = GraphTurnResultFactory.from_interrupt(
        payload,
        {},
        checkpoint_thread_id="conv:turn",
        hitl_blobs={"fire_detection": {"tool_call_records": []}},
    )
    assert "location" in result.data["needs_input"]
    assert result.data["checkpoint_thread_id"] == "conv:turn"
    assert result.data["hitl_blobs"]["fire_detection"]["tool_call_records"] == []
    assert result.data["interrupted"] is True


def test_graph_turn_result_factory_completed_state_with_location():
    state = GraphStateModel(
        final_answer="Done.",
        answer_source="domain_tools",
        selected_domains=["fire_detection"],
        resolved_location={"display_name": "Berlin", "lat": 52.5, "lon": 13.4},
    )
    result = GraphTurnResultFactory().from_completed_state(state)
    assert result.message == "Done."
    assert result.error is False
    assert result.city == "Berlin"
    assert result.coordinates == {"lat": 52.5, "lon": 13.4}


def test_fresh_turn_llm_history_appends_current_message():
    from eo_llm.adapters.bedrock.chat_history_context import (
        get_chat_history,
        reset_chat_history,
        set_chat_history,
    )

    current = UserMessage.create("Show fires there")
    request = GraphTurnRequest(
        thread_id="s1:turn",
        message=current,
        user_id="u1",
        session_id="s1",
        chat_history=[
            UserMessage.create("What about Berlin?"),
            AssistantMessage.create("Berlin is in Germany."),
        ],
    )
    token = set_chat_history(request.llm_chat_history())
    try:
        history = get_chat_history()
        assert len(history) == 3
        assert history[-1] is current
        assert history[0].content == "What about Berlin?"
    finally:
        reset_chat_history(token)


def test_resume_request_carries_persisted_chat_history():
    from langgraph.types import Command

    from src.db.models.message import InputResponseMessage
    from src.db.models.message_attachments import LocationAttachment
    from src.services.graph_runner.models import GraphResumeRequest

    prior = UserMessage.create("Floods in Paris")
    answer = InputResponseMessage.create(
        attachments=[LocationAttachment(name="Paris", coordinates=[48.8, 2.3])]
    )
    request = GraphResumeRequest(
        thread_id="conv:turn",
        message=answer,
        chat_history=[prior],
    )
    assert request.chat_history[0] is prior
    assert request.message is answer
    assert request.llm_chat_history() == [prior, answer]
    assert isinstance(request.to_graph_input(), Command)


def test_graph_turn_result_assistant_metadata():
    result = GraphTurnResult(message="Done.", error=True)
    meta = result.assistant_metadata()
    assert meta["error"] is True
    assert "artifacts" in meta
