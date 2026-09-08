"""Abstract user-input contracts: request, answer attachment, and kind registry."""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from src.db.models.message import InputRequestMessage
from src.db.models.message_attachments import MessageAttachment

from .types import InputKind


class UserInputRequest(BaseModel):
    """Base payload the server sends when requesting a user input."""

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")

    def to_message(self, *, kind: InputKind) -> InputRequestMessage:
        """Convert this single-kind request into an ``InputRequestMessage``."""
        needs = {kind: self.to_dict()}
        prompt = getattr(self, "prompt", None)
        return InputRequestMessage.create(
            content=str(prompt) if prompt else "Additional input required.",
            needs_input=needs,
        )


TRequest = TypeVar("TRequest", bound=UserInputRequest)
TResultAttachment = TypeVar("TResultAttachment", bound=MessageAttachment)


class UserInput(ABC, Generic[TRequest, TResultAttachment]):
    """Abstract user input: server asks with TRequest; client answers with an attachment.

    Subclasses register themselves by ``kind`` (same pattern as ``GraphNode``).
    """

    kind: ClassVar[InputKind]
    request_model: ClassVar[type[UserInputRequest]]
    attachment_model: ClassVar[type[MessageAttachment]]

    _registry: ClassVar[dict[str, type[UserInput[Any, Any]]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        kind = getattr(cls, "kind", None)
        if kind:
            UserInput._registry[kind] = cls

    @classmethod
    def for_kind(cls, kind: str) -> type[UserInput[Any, Any]]:
        input_cls = cls._registry.get(kind)
        if input_cls is None:
            raise ValueError(f"Unknown input kind: {kind!r}")
        return input_cls

    @classmethod
    def request_from_dict(cls, data: dict[str, Any] | BaseModel) -> TRequest:
        if isinstance(data, cls.request_model):
            return data  # type: ignore[return-value]
        return cls.request_model.model_validate(data)  # type: ignore[return-value]

    @classmethod
    def request_to_dict(cls, request: UserInputRequest) -> dict[str, Any]:
        return request.to_dict()

    @classmethod
    def apply_resume(
        cls,
        attachment: MessageAttachment,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update pause bookkeeping after the user answers this input kind."""
        needs_user_input = dict(state.get("needs_input") or {})
        needs_user_input.pop(cls.kind, None)
        state["needs_input"] = needs_user_input
        return state

    @classmethod
    def enrich_resumed_tool_result(
        cls,
        prior_data: dict[str, Any],
        attachment: MessageAttachment,
    ) -> tuple[str, dict[str, Any]]:
        """Build tool-result message + data after the user answers on resume.

        Subclasses override to add kind-specific context (e.g. the options that
        were offered). ``prior_data`` is the paused ``ToolResponse.data`` dict.
        """
        data = dict(prior_data)
        data.pop("stopped_for_user_input", None)
        data.pop("needs_input", None)
        data["user_answer"] = attachment.model_dump(mode="python")
        data["stopped_for_user_input"] = False
        return attachment.llm_text(), data
