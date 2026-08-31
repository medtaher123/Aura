"""Unit tests for chat turn helpers (pause state, language, ChatTurn)."""

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.api.chat.handlers import ChatTurn, NewChat, ResumeChat
from src.api.chat.language import to_english
from src.api.chat.pause_state import ConversationPauseState
from src.db.models.message import UserMessage
from src.services.graph_runner.models import GraphTurnRequest, GraphTurnResult


def test_conversation_pause_state_round_trip():
    turn = GraphTurnResult(
        message="Pick a place",
        data={
            "needs_input": {"location": {"candidates": [{"display_name": "Paris", "lat": 1, "lon": 2}]}},
            "checkpoint_thread_id": "conv:turn",
            "hitl_blobs": {
                "location_gate": {
                    "location_query": "Paris",
                    "location_candidates": [{"display_name": "Paris", "lat": 1, "lon": 2}],
                }
            },
        },
    )
    pause = ConversationPauseState.from_turn(
        turn,
        conversation_id="cid",
        detected_lang="fr",
        title_user_message="floods in Paris",
        conversation_title_pending=True,
        user_message_persisted=True,
        needs_input={"location": {"candidates": [{"display_name": "Paris", "lat": 1, "lon": 2}]}},
    )
    stored = pause.to_storage()
    loaded = ConversationPauseState.from_storage(stored)
    assert loaded is not None
    assert loaded.detected_lang == "fr"
    assert loaded.checkpoint_thread_id == "conv:turn"
    assert loaded.hitl_blobs["location_gate"]["location_query"] == "Paris"
    assert loaded.unpersisted_user_message() is None
    assert ConversationPauseState.from_storage(None) is None
    assert ConversationPauseState.from_storage({}) is None


def test_pause_state_rebuilds_unpersisted_user_message():
    pause = ConversationPauseState(
        user_message_persisted=False,
        title_user_message="floods in Paris",
    )
    message = pause.unpersisted_user_message()
    assert message is not None
    assert message.content == "floods in Paris"


def test_new_chat_and_resume_chat_extend_chat_turn():
    assert issubclass(NewChat, ChatTurn)
    assert issubclass(ResumeChat, ChatTurn)


def test_to_english_skips_when_already_english():
    text, lang = to_english("hello", "en")
    assert text == "hello"
    assert lang == "en"


class _FixedChat(ChatTurn):
    kind = "test"

    async def start(self) -> bool:
        return True


def test_chat_turn_complete_saves_user_and_assistant(monkeypatch):
    conversation_id = uuid4()
    user_message = UserMessage.create("hello")
    result = GraphTurnResult(message="Done.")

    class _Runner:
        async def execute(self, request):
            assert request.stream_emitter is not None
            return result

    conn = MagicMock()
    conn.is_closed = False
    conn.is_cancelled.return_value = False
    conn.send_status = AsyncMock()
    conn.send_complete = AsyncMock()
    conn.send_error = AsyncMock()

    conversations = MagicMock()
    conversations.append_messages = AsyncMock()

    @contextmanager
    def _bridge(_conn):
        yield object()

    monkeypatch.setattr("src.api.chat.handlers.stream_bridge", _bridge)
    monkeypatch.setattr(
        "src.api.chat.handlers.translate_from_english", lambda text, lang: text
    )

    chat = _FixedChat(conn, MagicMock(), conversations, graph_runner=_Runner())
    chat.conversation_id = conversation_id
    chat.graph_request = GraphTurnRequest(
        thread_id=f"{conversation_id}:turn",
        message=user_message,
        user_id="u1",
        session_id=str(conversation_id),
    )
    chat.user_query = "hello"
    chat.messages_to_save = [user_message]
    asyncio.run(chat.run())

    conn.send_complete.assert_awaited_once()
    conversations.append_messages.assert_awaited_once()
    persisted = conversations.append_messages.await_args.args[2]
    assert persisted[0] is user_message
    assert persisted[1].content == "Done."
