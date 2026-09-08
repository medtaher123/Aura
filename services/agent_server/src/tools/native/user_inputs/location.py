"""Native tool for the location user-input kind."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.geocode import search_location_candidates
from src.tools.contracts import ToolResponse
from src.user_inputs.location import LocationRequest, LocationUserInput

from .base import UserInputNativeTool


class RequestLocationUserInputTool(UserInputNativeTool):
    """Ask the user to choose a location from geocoding candidates.

    Returns a ``needs_input`` payload with ``location.candidates`` for the UI.

    ``candidates`` may be omitted when ``location_query`` is set; the tool
    geocodes that query and fills the candidate list.
    """

    tool_name = "request_location_user_input"
    user_input_cls = LocationUserInput

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        schema = dict(cls.request_model().model_json_schema())
        props = dict(schema.get("properties") or {})
        candidates = dict(props.get("candidates") or {})
        if candidates:
            candidates.pop("minItems", None)
            candidates["description"] = (
                "Optional location options for the user. If omitted or empty, "
                "candidates are filled by geocoding location_query."
            )
            props["candidates"] = candidates
        location_query = dict(props.get("location_query") or {})
        location_query["description"] = (
            "Place string to resolve. Required when candidates are omitted; "
            "used to auto-fill candidates via geocoding."
        )
        props["location_query"] = location_query
        schema["properties"] = props
        required = [
            name for name in (schema.get("required") or []) if name != "candidates"
        ]
        schema["required"] = required
        return schema

    def build_request(self, **kwargs: Any) -> LocationRequest:
        candidates = kwargs.get("candidates") or []
        return LocationRequest.from_candidates(
            candidates,
            prompt=kwargs.get("prompt"),
            location_query=kwargs.get("location_query"),
        )

    async def invoke(self, **kwargs: Any) -> ToolResponse:
        filled = await self._ensure_candidates(dict(kwargs))
        return super().invoke(**filled)

    @staticmethod
    async def _ensure_candidates(kwargs: dict[str, Any]) -> dict[str, Any]:
        candidates = kwargs.get("candidates") or []
        if isinstance(candidates, list) and candidates:
            return kwargs

        location_query = (
            str(kwargs.get("location_query") or kwargs.get("query") or "").strip()
        )
        if not location_query:
            raise ValueError(
                "request_location_user_input requires candidates or location_query"
            )

        found = await search_location_candidates(location_query, limit=8)
        if not found:
            raise ValueError(f"No locations found for query: {location_query!r}")

        kwargs["candidates"] = found
        kwargs["location_query"] = location_query
        if not kwargs.get("prompt"):
            kwargs["prompt"] = (
                f"Several places match {location_query!r}. Please choose a location."
            )
        return kwargs
