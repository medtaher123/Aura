"""Routes kind → request / attachment maps through the ``UserInput`` registry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from src.db.models.message import InputRequestMessage, InputResponseMessage
from src.db.models.message_attachments import (
    MessageAttachment,
    parse_attachments,
)

from .base import UserInput, UserInputRequest
from .types import InputKind


class UserInputRouter:
    """Routes kind → payload maps through the ``UserInput`` registry."""

    @classmethod
    def requests_from_dict(
        cls, raw: dict[str, Any] | None
    ) -> dict[InputKind, UserInputRequest]:
        if not isinstance(raw, dict) or not raw:
            return {}
        out: dict[InputKind, UserInputRequest] = {}
        for key, payload in raw.items():
            input_cls = UserInput.for_kind(str(key))
            kind: InputKind = input_cls.kind
            if isinstance(payload, BaseModel):
                out[kind] = input_cls.request_from_dict(
                    payload.model_dump(mode="python")
                )
            else:
                out[kind] = input_cls.request_from_dict(payload)
        return out

    @classmethod
    def requests_to_dict(cls, requests: dict[str, Any] | None) -> dict[str, Any]:
        typed = cls.requests_from_dict(requests)
        return {
            kind: UserInput.for_kind(kind).request_to_dict(model)
            for kind, model in typed.items()
        }

    @classmethod
    def to_request_message(
        cls, requests: dict[str, Any] | None
    ) -> InputRequestMessage:
        """Build one ``InputRequestMessage``; structure is source of truth."""
        typed = cls.requests_from_dict(requests)
        wire = {kind: req.to_dict() for kind, req in typed.items()}
        prompts = [
            str(req.prompt)
            for req in typed.values()
            if getattr(req, "prompt", None)
        ]
        return InputRequestMessage.create(
            content="\n".join(prompts) if prompts else "Additional input required.",
            needs_input=wire,
        )

    @classmethod
    def apply_resume_attachments(
        cls,
        attachments: list[Any] | None,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Pause bookkeeping from answered attachments (per registered kind)."""
        parsed = (
            attachments
            if attachments
            and all(isinstance(a, MessageAttachment) for a in attachments)
            else parse_attachments(attachments)  # type: ignore[arg-type]
        )
        for item in parsed:
            attachment_type = getattr(item, "type", None)
            if not isinstance(attachment_type, str):
                continue
            try:
                input_cls = UserInput.for_kind(attachment_type)
            except ValueError:
                continue
            input_cls.apply_resume(item, state, **kwargs)
        if not state.get("needs_input"):
            state["stopped_for_user_input"] = False
        return state
