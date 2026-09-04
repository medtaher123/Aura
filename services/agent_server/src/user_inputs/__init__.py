"""Typed user-input kinds (request / attachment answer / resume)."""

from __future__ import annotations

from typing import Any

from src.user_inputs.types import (
    InputKind,
    OTHER_OPTION_ID,
    OSMPrefixType,
    OSMType,
    get_osm_type_prefix,
)

__all__ = [
    "BoundingBoxRequest",
    "BoundingBoxUserInput",
    "InputKind",
    "LocationCandidate",
    "LocationRequest",
    "LocationUserInput",
    "MultipleChoiceOption",
    "MultipleChoiceRequest",
    "MultipleChoiceUserInput",
    "OTHER_OPTION_ID",
    "OSMPrefixType",
    "OSMType",
    "UserInput",
    "UserInputRequest",
    "UserInputRouter",
    "get_osm_type_prefix",
]

_kinds_registered = False


def _ensure_kinds_registered() -> None:
    """Import concrete kinds so ``UserInput.__init_subclass__`` registers them."""
    global _kinds_registered
    if _kinds_registered:
        return
    from src.user_inputs.bounding_box import BoundingBoxUserInput
    from src.user_inputs.location import LocationUserInput
    from src.user_inputs.multiple_choice import MultipleChoiceUserInput

    _ = (LocationUserInput, BoundingBoxUserInput, MultipleChoiceUserInput)
    _kinds_registered = True


def __getattr__(name: str) -> Any:
    if name in {"UserInput", "UserInputRequest"}:
        from src.user_inputs.base import UserInput, UserInputRequest

        return UserInput if name == "UserInput" else UserInputRequest
    if name in {
        "BoundingBoxRequest",
        "BoundingBoxUserInput",
        "LocationCandidate",
        "LocationRequest",
        "LocationUserInput",
        "MultipleChoiceOption",
        "MultipleChoiceRequest",
        "MultipleChoiceUserInput",
        "UserInputRouter",
    }:
        _ensure_kinds_registered()
        if name.startswith("BoundingBox"):
            from src.user_inputs import bounding_box as mod

            return getattr(mod, name)
        if name.startswith("Location") or name == "LocationCandidate":
            from src.user_inputs import location as mod

            return getattr(mod, name)
        if name.startswith("MultipleChoice"):
            from src.user_inputs import multiple_choice as mod

            return getattr(mod, name)
        from src.user_inputs.router import UserInputRouter

        return UserInputRouter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
