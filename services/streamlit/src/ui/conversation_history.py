"""Map API conversation messages into Streamlit chat session state."""

from __future__ import annotations

from typing import Literal, NotRequired

from typing_extensions import TypedDict

from src.models.tools import ToolArtifacts

ToolRunStatus = Literal["running", "success", "error", "skipped"]


class UserMessage(TypedDict):
    role: Literal["user"]
    content: str
    attachments: NotRequired[list[dict]]


class ToolCallRecord(TypedDict, total=False):
    tool_name: str
    status: ToolRunStatus
    step_id: str | None
    domain: str | None
    execution_time_seconds: float | None
    detail: str | None
    result: dict | None
    arguments: dict | None


class AssistantMessage(TypedDict, total=False):
    role: Literal["assistant"]
    content: str
    artifacts: ToolArtifacts
    error: bool
    tool_calls: list[ToolCallRecord]
    thinking_lines: list[str]


Message = UserMessage | AssistantMessage


def _shorten(text: str, *, max_len: int = 220) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def needs_input_from_message(message: dict) -> dict | None:
    needs = message.get("needs_input")
    if not isinstance(needs, dict):
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            needs = metadata.get("needs_input")
    if isinstance(needs, dict) and needs:
        return needs
    return None


def pending_from_conversation_messages(messages: list[dict]) -> dict | None:
    """Restore HITL pending state from the latest unanswered input_request."""
    for message in reversed(messages):
        kind = message.get("kind") or ""
        if kind == "input_response":
            return None
        if kind in ("assistant_text", "assistant"):
            return None
        if kind == "input_request":
            needs = needs_input_from_message(message)
            if needs:
                return {"needs_input": needs, "pause": {}}
            return None
    return None


def conversation_messages_to_chat_state(
    messages: list[dict],
) -> tuple[list[Message], list[dict]]:
    """Map API conversation messages into Streamlit UI + agent history.

    Persisted ``tool_call`` / ``tool_result`` pairs are buffered and attached to
    the following assistant message as ``tool_calls`` (same UX as live turns).
    """
    ui_messages: list[Message] = []
    agent_messages: list[dict] = []
    pending_tool_calls: list[ToolCallRecord] = []
    open_tool_call: dict | None = None

    def _flush_pending_tools() -> list[ToolCallRecord]:
        nonlocal pending_tool_calls
        flushed = list(pending_tool_calls)
        pending_tool_calls = []
        return flushed

    def _status_from_tool_result(meta: dict) -> ToolRunStatus:
        raw = str(meta.get("status") or "done")
        if raw == "error" or meta.get("error_message"):
            return "error"
        return "success"

    def _detail_from_tool_result(meta: dict) -> str | None:
        err = meta.get("error_message")
        if isinstance(err, str) and err.strip():
            return err.strip()
        result = meta.get("result")
        if isinstance(result, dict):
            msg = result.get("message")
            if isinstance(msg, str) and msg.strip():
                return _shorten(msg.strip(), max_len=160)
        return None

    for message in messages:
        kind = message.get("kind") or ""
        role = message.get("role")
        content = (message.get("content") or "").strip()
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        if kind == "tool_call":
            arguments = metadata.get("arguments")
            open_tool_call = {
                "tool_name": str(metadata.get("tool_name") or "tool"),
                "step_id": str(metadata.get("tool_use_id") or "") or None,
                "arguments": dict(arguments) if isinstance(arguments, dict) else None,
            }
            continue

        if kind == "tool_result":
            tool_name = "tool"
            step_id = str(metadata.get("tool_use_id") or "") or None
            arguments: dict | None = None
            if open_tool_call is not None:
                tool_name = open_tool_call.get("tool_name") or tool_name
                step_id = open_tool_call.get("step_id") or step_id
                raw_args = open_tool_call.get("arguments")
                arguments = dict(raw_args) if isinstance(raw_args, dict) else None
                open_tool_call = None
            latency_ms = metadata.get("latency_ms")
            execution_time: float | None = None
            if isinstance(latency_ms, (int, float)) and latency_ms >= 0:
                execution_time = float(latency_ms) / 1000.0
            raw_result = metadata.get("result")
            result_payload: dict | None
            if isinstance(raw_result, dict):
                result_payload = dict(raw_result)
            elif metadata.get("error_message"):
                result_payload = {
                    "error": True,
                    "error_message": metadata.get("error_message"),
                }
            else:
                result_payload = None
            record = ToolCallRecord(
                tool_name=tool_name,
                status=_status_from_tool_result(metadata),
                step_id=step_id,
                execution_time_seconds=execution_time,
                detail=_detail_from_tool_result(metadata),
            )
            if arguments is not None:
                record["arguments"] = arguments
            if result_payload is not None:
                record["result"] = result_payload
            pending_tool_calls.append(record)
            continue

        if kind in ("user_text", "input_response"):
            if pending_tool_calls or open_tool_call is not None:
                open_tool_call = None
                tools = _flush_pending_tools()
                if tools:
                    ui_messages.append(
                        AssistantMessage(
                            role="assistant",
                            content="",
                            artifacts=ToolArtifacts(),
                            error=False,
                            tool_calls=tools,
                        )
                    )
            attachments = message.get("attachments")
            if not isinstance(attachments, list):
                attachments = []
            if not content and not attachments:
                continue
            ui_messages.append(
                UserMessage(
                    role="user",
                    content=content,
                    attachments=attachments,
                )
            )
            agent_messages.append({"role": "user", "content": content})

        elif kind == "input_request":
            needs = needs_input_from_message(message)
            if not content and needs:
                content = "Additional input required."
            if not content:
                continue
            ui_messages.append(
                AssistantMessage(role="assistant", content=content, error=False)
            )
            agent_messages.append({"role": "assistant", "content": content})

        elif kind in ("assistant_text", "assistant") or role == "assistant":
            artifacts_data = metadata.get("artifacts")
            if isinstance(artifacts_data, dict):
                artifacts = ToolArtifacts(
                    maps=artifacts_data.get("maps", []),
                    thumbnails=artifacts_data.get("thumbnails", []),
                    urls=artifacts_data.get("urls", []),
                )
            else:
                artifacts = ToolArtifacts()
            tools = _flush_pending_tools()
            open_tool_call = None
            assistant_payload = AssistantMessage(
                role="assistant",
                content=content,
                artifacts=artifacts,
                error=bool(metadata.get("error", False)),
            )
            if tools:
                assistant_payload["tool_calls"] = tools
            ui_messages.append(assistant_payload)
            if content:
                agent_messages.append({"role": "assistant", "content": content})

    if pending_tool_calls:
        ui_messages.append(
            AssistantMessage(
                role="assistant",
                content="",
                artifacts=ToolArtifacts(),
                error=False,
                tool_calls=_flush_pending_tools(),
            )
        )

    return ui_messages, agent_messages
