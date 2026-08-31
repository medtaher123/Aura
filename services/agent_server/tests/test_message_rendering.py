"""Tests for message attachment presentation (LLM / frontend text)."""

from uuid import uuid4

from src.db.models.message import InputRequestMessage, UserMessage
from src.db.models.message_attachments import FileAttachment, LocationAttachment, parse_attachments


def test_attachment_owns_llm_text():
    loc = LocationAttachment(name="Paris", coordinates=[48.8, 2.3])
    assert "Paris" in loc.llm_text()
    assert "Confirmed location" in loc.llm_text()


def test_message_content_is_free_text_only():
    msg = UserMessage.create(
        "Flood damage",
        attachments=[LocationAttachment(name="Lyon", coordinates=[45.75, 4.85])],
    )
    assert msg.content == "Flood damage"
    assert msg.has_content
    empty = UserMessage.create(
        "",
        attachments=[LocationAttachment(name="Lyon", coordinates=[45.75, 4.85])],
    )
    assert empty.content == ""
    assert empty.has_content


def test_conversation_message_exposes_attachments():
    msg = UserMessage.create(
        "Flood damage",
        attachments=[LocationAttachment(name="Lyon", coordinates=[45.75, 4.85])],
    )
    msg.id = 1
    msg.conversation_id = __import__("uuid").uuid4()
    msg.timestamp = __import__("datetime").datetime.now(
        tz=__import__("datetime").timezone.utc
    )
    read = msg.to_frontend()
    assert read.kind == "user_text"
    assert read.role == "user"
    assert read.content == "Flood damage"
    assert len(read.attachments) == 1
    assert read.attachments[0]["type"] == "location"
    assert read.attachments[0]["name"] == "Lyon"
    assert read.to_dict()["attachments"][0]["name"] == "Lyon"

    req = InputRequestMessage.create(
        content="Choose",
        needs_input={
            "location": {
                "candidates": [{"display_name": "Paris", "lat": 48.8, "lon": 2.3}],
                "prompt": "Choose",
            }
        },
    )
    req.id = 2
    req.conversation_id = msg.conversation_id
    req.timestamp = msg.timestamp
    req_read = req.to_frontend()
    assert req_read.kind == "input_request"
    assert req_read.role == "assistant"
    assert req_read.needs_input is not None
    assert "location" in req_read.needs_input
    assert req_read.content == "Choose"


def test_file_attachment_points_at_files_table():
    file_id = uuid4()
    att = FileAttachment(file_id=file_id, name="brief.pdf")
    assert "brief.pdf" in att.llm_text()
    parsed = parse_attachments([att.model_dump(mode="json")])
    assert isinstance(parsed[0], FileAttachment)
    assert parsed[0].file_id == file_id
    assert parsed[0].name == "brief.pdf"

