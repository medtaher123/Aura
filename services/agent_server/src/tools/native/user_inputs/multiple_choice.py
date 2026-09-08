"""Native tool for the multiple-choice user-input kind."""

from __future__ import annotations

from typing import Any

from src.user_inputs.multiple_choice import (
    MultipleChoiceOption,
    MultipleChoiceRequest,
    MultipleChoiceUserInput,
)

from .base import UserInputNativeTool


class RequestMultipleChoiceUserInputTool(UserInputNativeTool):
    """Ask the user a multiple-choice question.

    The user picks one of ``options`` or, when ``allow_other`` is true (default),
    selects Other and types a custom answer. Set ``allow_other=false`` to restrict
    answers to the provided options only.
    """

    tool_name = "request_multiple_choice_user_input"
    user_input_cls = MultipleChoiceUserInput

    def build_request(self, **kwargs: Any) -> MultipleChoiceRequest:
        raw_options = kwargs.get("options") or []
        options: list[MultipleChoiceOption] = []
        for item in raw_options:
            if isinstance(item, MultipleChoiceOption):
                options.append(item)
            elif isinstance(item, dict):
                options.append(MultipleChoiceOption.model_validate(item))
            else:
                raise ValueError("each option must be an object with id and label")
        if len(options) < 2:
            raise ValueError("options must contain at least two entries")
        return MultipleChoiceRequest(
            prompt=kwargs.get("prompt"),
            options=options,
            allow_other=bool(kwargs.get("allow_other", True)),
            other_label=str(kwargs.get("other_label") or "Other"),
        )
