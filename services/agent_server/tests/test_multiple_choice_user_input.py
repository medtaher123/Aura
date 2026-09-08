"""Tests for multiple-choice user input (OCP extension)."""

from __future__ import annotations

import pytest

from src.db.models.message_attachments import MultipleChoiceAttachment, parse_attachments
from src.tools.native.user_inputs.multiple_choice import RequestMultipleChoiceUserInputTool
from src.user_inputs import (
    MultipleChoiceOption,
    MultipleChoiceRequest,
    MultipleChoiceUserInput,
    OTHER_OPTION_ID,
    UserInput,
    UserInputRouter,
)


def test_multiple_choice_registers_without_router_changes():
    assert UserInput.for_kind("multiple_choice") is MultipleChoiceUserInput
    assert MultipleChoiceUserInput.attachment_model is MultipleChoiceAttachment


def test_multiple_choice_request_validation():
    request = MultipleChoiceRequest(
        prompt="Pick a hazard layer",
        options=[
            MultipleChoiceOption(id="flood", label="Flood depth"),
            MultipleChoiceOption(id="fire", label="Fire perimeter"),
        ],
        allow_other=False,
    )
    assert request.allow_other is False
    dumped = UserInputRouter.requests_to_dict({"multiple_choice": request})
    assert dumped["multiple_choice"]["options"][0]["id"] == "flood"


def test_multiple_choice_request_rejects_reserved_option_id():
    with pytest.raises(ValueError, match="reserved"):
        MultipleChoiceRequest(
            options=[
                MultipleChoiceOption(id=OTHER_OPTION_ID, label="Bad"),
                MultipleChoiceOption(id="ok", label="OK"),
            ]
        )


def test_multiple_choice_tool_returns_needs_input_with_other_enabled():
    tool = RequestMultipleChoiceUserInputTool()
    response = tool.invoke(
        prompt="Which dataset?",
        options=[
            {"id": "sentinel2", "label": "Sentinel-2"},
            {"id": "landsat", "label": "Landsat"},
        ],
    )
    assert response.error is False
    assert response.data["input_kind"] == "multiple_choice"
    needs = response.data["needs_input"]["multiple_choice"]
    assert needs["allow_other"] is True
    assert len(needs["options"]) == 2


def test_multiple_choice_tool_can_disable_other():
    tool = RequestMultipleChoiceUserInputTool()
    response = tool.invoke(
        prompt="Strict pick",
        options=[
            {"id": "a", "label": "Option A"},
            {"id": "b", "label": "Option B"},
        ],
        allow_other=False,
    )
    assert response.data["needs_input"]["multiple_choice"]["allow_other"] is False


def test_multiple_choice_attachment_selected_option():
    attachment = MultipleChoiceAttachment(
        option_id="sentinel2",
        label="Sentinel-2",
    )
    assert "answered your multiple-choice question" in attachment.llm_text()
    assert "Sentinel-2" in attachment.llm_text()
    assert attachment.answer_summary() == "Selected option: Sentinel-2 (id=sentinel2)"


def test_multiple_choice_attachment_other_requires_custom_text():
    with pytest.raises(ValueError, match="custom_text"):
        MultipleChoiceAttachment(option_id=OTHER_OPTION_ID, label="Other")

    attachment = MultipleChoiceAttachment(
        option_id=OTHER_OPTION_ID,
        label="Other",
        custom_text="PlanetScope daily",
    )
    assert "custom response" in attachment.llm_text()
    assert attachment.answer_summary() == "Custom answer: PlanetScope daily"


def test_multiple_choice_round_trip_via_router():
    raw = {
        "multiple_choice": {
            "prompt": "Pick one",
            "options": [
                {"id": "a", "label": "Alpha"},
                {"id": "b", "label": "Beta"},
            ],
            "allow_other": True,
        }
    }
    requests = UserInputRouter.requests_from_dict(raw)
    assert isinstance(requests["multiple_choice"], MultipleChoiceRequest)
    assert requests["multiple_choice"].options[1].label == "Beta"


def test_resume_attachments_parse_multiple_choice():
    parsed = parse_attachments(
        [
            {
                "type": "multiple_choice",
                "option_id": OTHER_OPTION_ID,
                "label": "Other",
                "custom_text": "Custom layer",
            }
        ]
    )
    assert len(parsed) == 1
    assert parsed[0].type == "multiple_choice"
    assert parsed[0].custom_text == "Custom layer"


def test_multiple_choice_enrich_includes_offered_options():
    prior = {
        "needs_input": {
            "multiple_choice": {
                "prompt": "Which dataset?",
                "options": [
                    {"id": "s2", "label": "Sentinel-2"},
                    {"id": "ls", "label": "Landsat"},
                ],
                "allow_other": True,
            }
        },
        "input_kind": "multiple_choice",
        "stopped_for_user_input": True,
    }
    attachment = MultipleChoiceAttachment(
        option_id="s2",
        label="Sentinel-2",
    )
    message, data = MultipleChoiceUserInput.enrich_resumed_tool_result(prior, attachment)
    assert "USER INPUT RECEIVED" in message
    assert "Answer:" in message
    assert "Sentinel-2" in message
    assert "[ls] Landsat" in message
    assert data["user_input_received"] is True
    assert data["status"] == "answered"
    assert data["answer_summary"] == "Selected option: Sentinel-2 (id=s2)"
    assert data["user_answer"]["selected_option_id"] == "s2"
    assert data["question"]["options"] == prior["needs_input"]["multiple_choice"]["options"]
    assert "needs_input" not in data


def test_multiple_choice_enrich_uses_attachment_context():
    attachment = MultipleChoiceAttachment(
        option_id="flood",
        label="Flood depth",
        prompt="Pick a layer",
        offered_options=[
            {"id": "flood", "label": "Flood depth"},
            {"id": "fire", "label": "Fire perimeter"},
        ],
        allow_other=False,
    )
    message, data = MultipleChoiceUserInput.enrich_resumed_tool_result({}, attachment)
    assert "Pick a layer" in message
    assert "[fire] Fire perimeter" in message
    assert OTHER_OPTION_ID not in message
    assert data["question"]["allow_other"] is False


def test_with_user_input_answers_multiple_choice_includes_question():
    from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord
    from eo_llm.graph.nodes.domain_base import AgenticDomainNode
    from src.tools.contracts import ToolResponse

    record = AgentToolCallRecord(
        tool_use_id="mc-1",
        tool_name="request_multiple_choice_user_input",
        result=ToolResponse(
            tool_name="request_multiple_choice_user_input",
            message="Pick one",
            data={
                "needs_input": {
                    "multiple_choice": {
                        "prompt": "Which mode?",
                        "options": [
                            {"id": "quick", "label": "Quick"},
                            {"id": "full", "label": "Full"},
                        ],
                    }
                },
                "stopped_for_user_input": True,
                "input_kind": "multiple_choice",
            },
        ),
    )
    patched = AgenticDomainNode._with_user_input_answers(
        [record],
        [
            {
                "type": "multiple_choice",
                "option_id": "full",
                "label": "Full",
            }
        ],
    )
    assert patched[0].result is not None
    assert "USER INPUT RECEIVED" in patched[0].result.message
    assert patched[0].result.data["user_input_received"] is True
    assert patched[0].result.data["user_answer"]["selected_option_id"] == "full"
    assert "[quick] Quick" in patched[0].result.message
