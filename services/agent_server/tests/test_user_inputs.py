"""Tests for spatial area and user-input schemas."""

from __future__ import annotations

import pytest

from src.db.models.message import (
    AssistantMessage,
    InputRequestMessage,
    InputResponseMessage,
    UserMessage,
)
from src.db.models.message_attachments import (
    BoundingBoxAttachment,
    LocationAttachment,
)
from src.schemas.spatial import BoundingBox
from src.user_inputs import (
    BoundingBoxRequest,
    LocationCandidate,
    LocationRequest,
    LocationUserInput,
    BoundingBoxUserInput,
    UserInput,
    UserInputRequest,
    UserInputRouter,
)


def test_bounding_box_helpers():
    box = BoundingBox(min_lat=48.0, max_lat=49.0, min_lon=2.0, max_lon=3.0)
    assert box.as_list() == [48.0, 49.0, 2.0, 3.0]
    assert box.centroid() == (48.5, 2.5)
    assert BoundingBox.from_list(box.as_list()).as_list() == box.as_list()


def test_user_input_registry():
    assert UserInput.for_kind("location") is LocationUserInput
    assert UserInput.for_kind("bounding_box") is BoundingBoxUserInput
    with pytest.raises(ValueError):
        UserInput.for_kind("unknown")


def test_request_attachment_models():
    assert issubclass(LocationRequest, UserInputRequest)
    assert issubclass(BoundingBoxRequest, UserInputRequest)
    assert LocationUserInput.attachment_model is LocationAttachment
    assert BoundingBoxUserInput.attachment_model is BoundingBoxAttachment


def test_needs_input_round_trip_via_router():
    raw = {
        "location": {
            "candidates": [
                {"display_name": "Paris", "lat": 48.8, "lon": 2.3},
            ],
            "prompt": "Pick one",
        },
        "bounding_box": {
            "prompt": "Draw area",
            "map_center": [46.5, 2.5],
            "map_zoom": 6,
        },
    }
    requests = UserInputRouter.requests_from_dict(raw)
    assert isinstance(requests["location"], LocationRequest)
    assert isinstance(requests["bounding_box"], BoundingBoxRequest)
    dumped = UserInputRouter.requests_to_dict(requests)
    assert dumped["location"]["candidates"][0]["display_name"] == "Paris"


def test_location_request_from_candidates():
    request = LocationRequest.from_candidates(
        [
            {"display_name": "Paris", "lat": 48.8, "lon": 2.3, "class": "place"},
            LocationCandidate(display_name="Lyon", lat=45.7, lon=4.8),
        ],
        prompt="Pick one",
        location_query="France",
    )
    assert len(request.candidates) == 2
    assert request.location_query == "France"
    assert request.to_dict()["candidates"][0]["display_name"] == "Paris"


def test_graph_turn_pending_input_requests():
    from src.services.graph_runner.models import GraphTurnResult

    turn = GraphTurnResult(
        message="Pick a place",
        data={
            "needs_input": {
                "location": {
                    "candidates": [{"display_name": "Paris", "lat": 48.8, "lon": 2.3}],
                }
            },
            "checkpoint_thread_id": "conv:turn",
        },
    )
    pending = turn.pending_input_requests()
    assert "location" in pending
    assert pending["location"]["candidates"][0]["display_name"] == "Paris"
    assert turn.data["checkpoint_thread_id"] == "conv:turn"
    assert GraphTurnResult(message="done").pending_input_requests() == {}


def test_apply_bounding_box_attachment_seeds_area():
    state: dict = {}
    BoundingBoxAttachment(
        area={
            "kind": "bounding_box",
            "min_lat": 1.0,
            "max_lat": 2.0,
            "min_lon": 3.0,
            "max_lon": 4.0,
        }
    ).apply_to_state(state)
    assert state["resolved_area"]["min_lat"] == 1.0
    assert state["resolved_location"]["lat"] == 1.5


def test_apply_location_attachment_seeds_resolved_location():
    """Attachment only seeds location data; pause flags are untouched."""
    state: dict = {
        "needs_input": {"bounding_box": {"prompt": "draw"}},
        "stopped_for_user_input": True,
    }
    attachment = LocationAttachment(
        name="Paris, France",
        coordinates=[48.8566, 2.3522],
        osm_id=7444,
        osm_type="relation",
        osm_type_prefix="R",
    )
    attachment.apply_to_state(state)
    assert state["resolved_location"]["display_name"] == "Paris, France"
    assert state["resolved_location"]["lat"] == 48.8566
    assert state["resolved_location"]["lon"] == 2.3522
    assert "confirmed_location_index" not in state
    assert state["needs_input"] == {"bounding_box": {"prompt": "draw"}}
    assert state["stopped_for_user_input"] is True


def test_apply_resume_needs_input_clears_answered_kinds():
    """Each input kind owns its resume bookkeeping via apply_resume."""
    state: dict = {
        "location_candidates": [
            {"display_name": "Lyon", "lat": 45.75, "lon": 4.85},
            {"display_name": "Paris", "lat": 48.8, "lon": 2.3, "osm_id": 7444},
        ],
        "needs_input": {
            "location": {
                "candidates": [
                    {"display_name": "Lyon", "lat": 45.75, "lon": 4.85},
                    {"display_name": "Paris", "lat": 48.8, "lon": 2.3, "osm_id": 7444},
                ],
                "prompt": "Pick one",
            }
        },
        "stopped_for_user_input": True,
    }
    attachment = LocationAttachment(
        name="Paris", coordinates=[48.8, 2.3], osm_id=7444
    )
    UserInputRouter.apply_resume_attachments([attachment], state)
    assert state["confirmed_location_index"] == 1
    assert state["needs_input"] == {}
    assert state["stopped_for_user_input"] is False


def test_resume_applies_needs_input_then_attachment_data():
    """Resume: clear pause kinds, then attachments seed resolved location."""
    from src.db.models.message_attachments import apply_attachments

    state: dict = {
        "needs_input": {
            "location": {
                "candidates": [
                    {"display_name": "Paris", "lat": 48.8, "lon": 2.3},
                ],
                "prompt": "Pick one",
            }
        },
        "stopped_for_user_input": True,
    }
    attachments = [
        LocationAttachment(name="Paris", coordinates=[48.8, 2.3]),
    ]
    UserInputRouter.apply_resume_attachments(attachments, state)
    apply_attachments(attachments, state)
    assert state["confirmed_location_index"] == 0
    assert state["needs_input"] == {}
    assert state["stopped_for_user_input"] is False
    assert state["resolved_location"]["display_name"] == "Paris"


def test_chat_request_message_to_user_message():
    from src.schemas.websocket import ChatRequestMessage

    msg = ChatRequestMessage(
        message="Estimate flood damage",
        attachments=[
            {
                "type": "bounding_box",
                "area": {
                    "kind": "bounding_box",
                    "min_lat": 48.0,
                    "max_lat": 49.0,
                    "min_lon": 2.0,
                    "max_lon": 3.0,
                },
            }
        ],
    )
    assert len(msg.attachments) == 1
    assert msg.attachments[0].type == "bounding_box"
    assert msg.attachments[0].area["min_lat"] == 48.0

    user_message = msg.to_message()
    assert user_message.content == "Estimate flood damage"
    assert len(user_message.attachments) == 1
    assert user_message.attachments[0].type == "bounding_box"


def test_chat_resume_message_to_input_response():
    import uuid

    from src.schemas.websocket import ChatResumeMessage

    msg = ChatResumeMessage(
        conversation_id=uuid.uuid4(),
        attachments=[
            {
                "type": "location",
                "name": "Paris",
                "coordinates": [48.85, 2.35],
            }
        ],
    )
    input_message = msg.to_message()
    assert input_message.kind == "input_response"
    assert len(input_message.attachments) == 1
    assert input_message.attachments[0].type == "location"
    assert input_message.attachments[0].name == "Paris"


def test_graph_turn_request_applies_attachments():
    from src.db.models.message import UserMessage
    from src.services.graph_runner.models import GraphTurnRequest

    loc = LocationAttachment(name="Lyon", coordinates=[45.75, 4.85])
    req = GraphTurnRequest(
        thread_id="s1:turn",
        message=UserMessage.create("Flood damage here", attachments=[loc]),
        user_id="u1",
        session_id="s1",
    )
    state = req.to_graph_input()
    assert state["user_query"] == "Flood damage here"
    assert state["resolved_location"]["display_name"] == "Lyon"
    assert state["resolved_location"]["lat"] == 45.75


def test_invalid_bbox_order_raises():
    with pytest.raises(ValueError):
        BoundingBox(min_lat=49.0, max_lat=48.0, min_lon=2.0, max_lon=3.0)


def test_request_to_message():
    request = LocationRequest.from_candidates(
        [{"display_name": "Paris", "lat": 48.8, "lon": 2.3}],
        prompt="Pick a city",
    )
    msg = request.to_message(kind="location")
    assert isinstance(msg, InputRequestMessage)
    assert msg.role == "assistant"
    assert msg.kind == "input_request"
    assert msg.content == "Pick a city"
    frontend = msg.to_frontend()
    assert frontend.kind == "input_request"
    assert frontend.role == "assistant"
    assert frontend.needs_input is not None and "location" in frontend.needs_input
    assert msg.needs_input["location"]["prompt"] == "Pick a city"


def test_attachment_to_response_message():
    msg = InputResponseMessage.create(
        attachments=[LocationAttachment(name="Paris", coordinates=[48.8, 2.3])]
    )
    assert isinstance(msg, InputResponseMessage)
    assert msg.role == "user"
    assert msg.kind == "input_response"
    assert len(msg.attachments) == 1
    assert msg.attachments[0].type == "location"
    assert msg.content == ""
    assert msg.has_content
    assert msg.to_frontend().kind == "input_response"
    assert msg.to_frontend().content == ""


def test_router_to_request_and_response_messages():
    requests = {
        "location": {
            "candidates": [{"display_name": "Paris", "lat": 48.8, "lon": 2.3}],
            "prompt": "Pick one",
        }
    }
    req_msg = UserInputRouter.to_request_message(requests)
    assert isinstance(req_msg, InputRequestMessage)
    assert "location" in req_msg.needs_input
    assert req_msg.content == "Pick one"

    res_msg = InputResponseMessage.create(
        attachments=[LocationAttachment(name="Paris", coordinates=[48.8, 2.3])]
    )
    assert isinstance(res_msg, InputResponseMessage)
    assert len(res_msg.attachments) == 1
    assert res_msg.attachments[0].type == "location"
    assert res_msg.content == ""
    assert res_msg.has_content
    res_msg.content = ""
    assert res_msg.content == ""
    assert res_msg.attachments[0].name == "Paris"


def test_orm_message_create_helpers():
    user = UserMessage.create("hello")
    assert user.role == "user"
    assert user.kind == "user_text"
    assert user.content == "hello"

    with_inputs = UserMessage.create(
        "Flood damage here",
        attachments=[LocationAttachment(name="Lyon", coordinates=[45.75, 4.85])],
    )
    assert len(with_inputs.attachments) == 1
    assert with_inputs.attachments[0].type == "location"
    assert with_inputs.content == "Flood damage here"
    frontend = with_inputs.to_frontend()
    assert frontend.attachments
    assert frontend.attachments[0]["name"] == "Lyon"
    assert frontend.content == "Flood damage here"

    assistant = AssistantMessage.create("hi", metadata={"k": 1})
    assert assistant.role == "assistant"
    assert assistant.kind == "assistant_text"
    assert assistant.message_metadata["k"] == 1
    assert assistant.to_frontend().kind == "assistant_text"


