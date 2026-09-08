"""Native tool for the bounding-box user-input kind."""

from __future__ import annotations

from typing import Any

from src.user_inputs.bounding_box import BoundingBoxRequest, BoundingBoxUserInput

from .base import UserInputNativeTool


class RequestBoundingBoxUserInputTool(UserInputNativeTool):
    """Ask the user to draw a bounding box on the map.

    Returns a ``needs_input`` payload with optional map center / zoom hints.
    """

    tool_name = "request_bounding_box_user_input"
    user_input_cls = BoundingBoxUserInput

    def build_request(self, **kwargs: Any) -> BoundingBoxRequest:
        return BoundingBoxRequest(
            prompt=kwargs.get("prompt"),
            map_center=kwargs.get("map_center"),
            map_zoom=kwargs.get("map_zoom"),
        )
