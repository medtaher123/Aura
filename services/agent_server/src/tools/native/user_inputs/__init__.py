"""Native tools that request user input (auto-registered on import)."""

from src.tools.native.user_inputs.bounding_box import RequestBoundingBoxUserInputTool
from src.tools.native.user_inputs.location import RequestLocationUserInputTool

__all__ = [
    "RequestBoundingBoxUserInputTool",
    "RequestLocationUserInputTool",
]
