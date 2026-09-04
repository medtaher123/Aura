"""Tests for tool call/result message persistence."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord, ConverseResponse, LLMProvider
from eo_llm.adapters.bedrock.llm_providers.bedrockProvider import BedrockProvider
from eo_llm.graph.state import GraphStateModel

from src.db.base import BaseModel
from src.db.models.conversation import Conversation
from src.db.models.message import (
    AssistantMessage,
    MessageKind,
    ToolCallMessage,
    ToolResultMessage,
    UserMessage,
    message_from_graph_dump,
)
from src.db.models.user import User
from src.db.repositories.messages import MessageRepository
from src.services.graph_runner.responses import GraphTurnResultFactory
from src.tools.contracts import ToolResponse


def test_agent_tool_call_record_to_messages_visible_to_ui_temporarily():
    record = AgentToolCallRecord(
        tool_use_id="use-1",
        turn_index=2,
        tool_name="calculator",
        arguments={"expression": "1+1"},
        status="done",
        latency_ms=12,
        result=ToolResponse(message="2", tool_name="calculator", data={"value": 2}),
    )
    call_msg, result_msg = record.to_messages()
    assert isinstance(call_msg, ToolCallMessage)
    assert isinstance(result_msg, ToolResultMessage)
    # Temporary: tool rows are UI-visible for debugging.
    assert call_msg.visible_to_ui is True
    assert result_msg.visible_to_ui is True
    assert call_msg.kind == MessageKind.TOOL_CALL.value
    assert result_msg.kind == MessageKind.TOOL_RESULT.value
    assert call_msg.message_metadata["tool_name"] == "calculator"
    assert call_msg.message_metadata["turn_index"] == 2
    assert result_msg.message_metadata["result"]["data"]["value"] == 2


def test_tool_message_graph_dump_round_trip():
    record = AgentToolCallRecord(
        tool_use_id="use-2",
        tool_name="web_search_tool",
        arguments={"q": "flood"},
        status="error",
        error_message="timeout",
    )
    dumps = [m.dump_for_graph() for m in record.to_messages()]
    rehydrated = [message_from_graph_dump(d) for d in dumps]
    assert rehydrated[0].kind == MessageKind.TOOL_CALL.value
    assert rehydrated[1].kind == MessageKind.TOOL_RESULT.value
    assert rehydrated[0].visible_to_ui is True
    assert rehydrated[1].message_metadata["error_message"] == "timeout"


def test_llm_provider_formats_tool_messages():
    class _Stub(LLMProvider):
        @property
        def name(self) -> str:
            return "stub"

        async def call_structured(self, **kwargs):
            return None

        async def call_stream(self, **kwargs):
            if False:
                yield ""

        async def call_standard_with_document(self, **kwargs):
            return {}

        async def call_converse(self, **kwargs):
            return ConverseResponse(stop_reason="end_turn", text="ok")

        async def call_converse_stream(self, **kwargs):
            return ConverseResponse(stop_reason="end_turn", text="ok")

    record = AgentToolCallRecord(
        tool_use_id="tid",
        tool_name="calculator",
        arguments={"expression": "2+2"},
        status="done",
        result=ToolResponse(message="4", tool_name="calculator"),
    )
    formatted = _Stub().format_messages(record.to_messages())
    assert len(formatted) == 2
    assert formatted[0]["role"] == "assistant"
    assert formatted[0]["content"][0]["toolUse"]["toolUseId"] == "tid"
    assert formatted[0]["content"][0]["toolUse"]["name"] == "calculator"
    assert formatted[1]["role"] == "user"
    assert formatted[1]["content"][0]["toolResult"]["toolUseId"] == "tid"
    assert formatted[1]["content"][0]["toolResult"]["status"] == "success"


def test_bedrock_provider_formats_tool_messages():
    record = AgentToolCallRecord(
        tool_use_id="tid",
        tool_name="calculator",
        arguments={"expression": "2+2"},
        status="done",
        result=ToolResponse(message="4", tool_name="calculator"),
    )
    formatted = BedrockProvider().format_messages(record.to_messages())
    assert len(formatted) == 2
    assert formatted[0]["role"] == "assistant"
    assert formatted[0]["content"][0]["toolUse"]["toolUseId"] == "tid"
    assert formatted[0]["content"][0]["toolUse"]["name"] == "calculator"
    assert formatted[1]["role"] == "user"
    assert formatted[1]["content"][0]["toolResult"]["toolUseId"] == "tid"
    assert formatted[1]["content"][0]["toolResult"]["status"] == "success"


@pytest.mark.asyncio
async def test_bedrock_provider_filters_tool_messages_without_tool_config():
    record = AgentToolCallRecord(
        tool_use_id="tid",
        tool_name="calculator",
        arguments={"expression": "2+2"},
        status="done",
        result=ToolResponse(message="4", tool_name="calculator"),
    )
    chat_history = [UserMessage.create("hello"), *record.to_messages()]

    filtered = await BedrockProvider().format_converse_messages(
        chat_history=chat_history
    )

    assert len(filtered) == 1
    assert filtered[0]["role"] == "user"
    assert filtered[0]["content"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_bedrock_provider_keeps_tool_messages_when_enabled():
    record = AgentToolCallRecord(
        tool_use_id="tid",
        tool_name="calculator",
        arguments={"expression": "2+2"},
        status="done",
        result=ToolResponse(message="4", tool_name="calculator"),
    )
    chat_history = [UserMessage.create("hello"), *record.to_messages()]

    formatted = await BedrockProvider().format_converse_messages(
        chat_history=chat_history,
        include_tool_messages=True,
    )

    assert len(formatted) == 3
    assert formatted[1]["content"][0]["toolUse"]["toolUseId"] == "tid"
    assert formatted[2]["content"][0]["toolResult"]["toolUseId"] == "tid"


def test_graph_turn_result_factory_collects_tool_messages_on_complete():
    record = AgentToolCallRecord(
        tool_use_id="t1",
        tool_name="calculator",
        arguments={},
        result=ToolResponse(message="ok", tool_name="calculator"),
    )
    tool_messages = [m.dump_for_graph() for m in record.to_messages()]
    state = GraphStateModel(
        final_answer="Done.",
        answer_source="domain_tools",
        selected_domains=["agentic_test"],
        domain_results={
            "agentic_test": {
                "status": "done",
                "message": "Done.",
                "tool_messages": tool_messages,
            }
        },
    )
    result = GraphTurnResultFactory().from_completed_state(state)
    assert len(result.tool_messages) == 2
    assert result.tool_messages[0].kind == MessageKind.TOOL_CALL.value
    assert result.tool_messages[1].kind == MessageKind.TOOL_RESULT.value


def test_graph_turn_result_factory_interrupt_has_no_tool_messages():
    result = GraphTurnResultFactory.from_interrupt(
        {"prompt": "Need input", "data": {"needs_input": {"location": {}}}},
        {},
        checkpoint_thread_id="c:t",
    )
    assert result.tool_messages == []
    assert result.data["interrupted"] is True


@pytest.mark.asyncio
async def test_message_repository_filters_visible_to_ui():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        user = User(id="u1", provider="test", email="u@t.com", username="u1")
        db.add(user)
        await db.flush()
        conversation = Conversation(id=uuid4(), user_id=user.id, title="t")
        db.add(conversation)
        await db.flush()

        repo = MessageRepository(db)
        await repo.create_for_conversation(
            conversation.id, UserMessage.create("hello"), commit=False
        )
        record = AgentToolCallRecord(
            tool_use_id="x",
            tool_name="calculator",
            arguments={},
            result=ToolResponse(message="1", tool_name="calculator"),
        )
        for msg in record.to_messages():
            await repo.create_for_conversation(conversation.id, msg, commit=False)
        await repo.create_for_conversation(
            conversation.id, AssistantMessage.create("answer"), commit=False
        )
        from src.db.models.message import InputRequestMessage, InputResponseMessage

        await repo.create_for_conversation(
            conversation.id,
            InputRequestMessage.create("Pick a place", needs_input={"location": {}}),
            commit=False,
        )
        await repo.create_for_conversation(
            conversation.id,
            InputResponseMessage.create(attachments=[]),
            commit=False,
        )
        await db.commit()

        visible = await repo.list_for_conversation(conversation.id)
        assert [m.kind for m in visible] == [
            MessageKind.USER_TEXT.value,
            MessageKind.TOOL_CALL.value,
            MessageKind.TOOL_RESULT.value,
            MessageKind.ASSISTANT_TEXT.value,
            MessageKind.INPUT_REQUEST.value,
            MessageKind.INPUT_RESPONSE.value,
        ]

        all_msgs = await repo.list_for_conversation(
            conversation.id, visible_to_ui=None
        )
        assert [m.kind for m in all_msgs] == [
            MessageKind.USER_TEXT.value,
            MessageKind.TOOL_CALL.value,
            MessageKind.TOOL_RESULT.value,
            MessageKind.ASSISTANT_TEXT.value,
            MessageKind.INPUT_REQUEST.value,
            MessageKind.INPUT_RESPONSE.value,
        ]

        for_agent = await repo.list_for_conversation(
            conversation.id, visible_to_ui=None, visible_to_agent=True
        )
        assert [m.kind for m in for_agent] == [
            MessageKind.USER_TEXT.value,
            MessageKind.TOOL_CALL.value,
            MessageKind.TOOL_RESULT.value,
            MessageKind.ASSISTANT_TEXT.value,
        ]

    await engine.dispose()


def test_input_messages_hidden_from_agent():
    from src.db.models.message import InputRequestMessage, InputResponseMessage

    req = InputRequestMessage.create("Choose", needs_input={"location": {}})
    resp = InputResponseMessage.create()
    assert req.visible_to_agent is False
    assert resp.visible_to_agent is False
    assert req.visible_to_ui is True
    assert resp.visible_to_ui is True
    assert UserMessage.create("hi").visible_to_agent is True
    assert AssistantMessage.create("ok").visible_to_agent is True
