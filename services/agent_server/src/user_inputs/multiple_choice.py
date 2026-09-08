"""Multiple-choice user-input kind: pick one option or type a custom answer."""

from __future__ import annotations

from typing import Any, ClassVar, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.db.models.message_attachments import MessageAttachment, MultipleChoiceAttachment

from .base import UserInput, UserInputRequest
from .types import InputKind, OTHER_OPTION_ID


class MultipleChoiceOption(BaseModel):
    """One selectable option presented to the user."""

    id: str = Field(..., description="Stable option id returned in the answer")
    label: str = Field(..., description="Human-readable option label")

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        option_id = str(value).strip()
        if not option_id:
            raise ValueError("option id must be non-empty")
        if option_id == OTHER_OPTION_ID:
            raise ValueError(f"option id {OTHER_OPTION_ID!r} is reserved")
        return option_id

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        label = str(value).strip()
        if not label:
            raise ValueError("option label must be non-empty")
        return label


class MultipleChoiceRequest(UserInputRequest):
    """Payload the server sends when requesting a multiple-choice answer."""

    prompt: Optional[str] = Field(default=None, description="Question shown to the user")
    options: list[MultipleChoiceOption] = Field(
        ...,
        min_length=2,
        description="Selectable options (at least two)",
    )
    allow_other: bool = Field(
        default=True,
        description="When true, the user may pick Other and type a custom answer",
    )
    other_label: str = Field(
        default="Other",
        description="Label for the custom-answer option when allow_other is true",
    )

    @model_validator(mode="after")
    def validate_unique_option_ids(self) -> MultipleChoiceRequest:
        ids = [option.id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("option ids must be unique")
        return self


class MultipleChoiceUserInput(
    UserInput[MultipleChoiceRequest, MultipleChoiceAttachment]
):
    kind: ClassVar[InputKind] = "multiple_choice"
    request_model: ClassVar[type[UserInputRequest]] = MultipleChoiceRequest
    attachment_model: ClassVar[type[MessageAttachment]] = MultipleChoiceAttachment

    @classmethod
    def enrich_resumed_tool_result(
        cls,
        prior_data: dict[str, Any],
        attachment: MessageAttachment,
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(attachment, MultipleChoiceAttachment):
            return super().enrich_resumed_tool_result(prior_data, attachment)

        paused_request = (prior_data.get("needs_input") or {}).get(cls.kind) or {}
        prompt = attachment.prompt or paused_request.get("prompt")
        options = attachment.offered_options or paused_request.get("options") or []
        allow_other = (
            attachment.allow_other
            if attachment.offered_options is not None
            else paused_request.get("allow_other", True)
        )
        other_label = attachment.other_label or paused_request.get("other_label") or "Other"

        question = {
            "prompt": prompt,
            "options": options,
            "allow_other": allow_other,
            "other_label": other_label,
        }
        answer_summary = attachment.answer_summary()
        message = cls._format_answer_message(question, attachment, answer_summary)
        data = dict(prior_data)
        data.pop("stopped_for_user_input", None)
        data.pop("needs_input", None)
        data["input_kind"] = cls.kind
        data["user_input_received"] = True
        data["status"] = "answered"
        data["answer_summary"] = answer_summary
        data["question"] = question
        data["user_answer"] = cls._wire_user_answer(attachment)
        data["stopped_for_user_input"] = False
        return message, data

    @staticmethod
    def _wire_user_answer(attachment: MultipleChoiceAttachment) -> dict[str, Any]:
        out: dict[str, Any] = {
            "selected_option_id": attachment.option_id,
            "selected_label": attachment.label,
            "is_other": attachment.option_id == OTHER_OPTION_ID,
        }
        if attachment.custom_text:
            out["custom_text"] = attachment.custom_text
        return out

    @staticmethod
    def _format_answer_message(
        question: dict[str, Any],
        attachment: MultipleChoiceAttachment,
        answer_summary: str,
    ) -> str:
        lines: list[str] = [
            "USER INPUT RECEIVED — the user answered your multiple-choice question.",
            f"Answer: {answer_summary}",
            "",
            "Use this answer and continue the task.",
        ]
        prompt = question.get("prompt")
        options = question.get("options") or []
        if prompt or options:
            lines.extend(["", "Question context:"])
        if prompt:
            lines.append(f"  Prompt: {prompt}")
        if options:
            lines.append("  Options that were shown:")
            for option in options:
                if isinstance(option, dict):
                    lines.append(
                        f"    - [{option.get('id')}] {option.get('label')}"
                    )
            if question.get("allow_other", True):
                lines.append(
                    f"    - [{OTHER_OPTION_ID}] {question.get('other_label') or 'Other'}"
                )
        return "\n".join(lines)
