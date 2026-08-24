"""Native tool for the location user-input kind."""

from __future__ import annotations

from typing import Any

from src.user_inputs.location import LocationRequest, LocationUserInput

from .base import UserInputNativeTool


class RequestLocationUserInputTool(UserInputNativeTool):
    """Ask the user to choose a location from geocoding candidates.

    Returns a ``needs_input`` payload with ``location.candidates`` for the UI.
    """

    tool_name = "request_location_user_input"
    user_input_cls = LocationUserInput

    def build_request(self, **kwargs: Any) -> LocationRequest:
        candidates = kwargs.get("candidates") or []
        return LocationRequest.from_candidates(
            candidates,
            prompt=kwargs.get("prompt"),
            location_query=kwargs.get("location_query"),
        )

