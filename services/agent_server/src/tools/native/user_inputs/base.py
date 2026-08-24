"""Base class for native tools that pause the turn and request user input."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from src.tools.contracts import ToolResponse
from src.tools.native.base import NativeTool
from src.user_inputs.base import UserInput, UserInputRequest
from src.user_inputs.router import UserInputRouter


class UserInputNativeTool(NativeTool):
    """Native tool that emits a ``needs_input`` payload for one user-input kind."""

    user_input_cls: ClassVar[type[UserInput[Any, Any]]]

    @classmethod
    def request_model(cls) -> type[UserInputRequest]:
        return cls.user_input_cls.request_model

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        """JSON Schema from the linked user-input request model."""
        return cls.request_model().model_json_schema()

    @abstractmethod
    def build_request(self, **kwargs: Any) -> UserInputRequest:
        """Build the wire payload sent to the client for this input kind."""

    def invoke(self, **kwargs: Any) -> ToolResponse:
        request = self.build_request(**kwargs)
        kind = self.user_input_cls.kind
        needs_input = UserInputRouter.requests_to_dict({kind: request})
        prompt = getattr(request, "prompt", None) or f"Additional input required ({kind})."
        return ToolResponse(
            tool_name=self.tool_name,
            message=str(prompt),
            data={
                "needs_input": needs_input,
                "stopped_for_user_input": True,
                "input_kind": kind,
            },
            error=False,
        )
