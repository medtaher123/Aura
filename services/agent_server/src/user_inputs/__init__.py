"""Typed user-input kinds (request / attachment answer / resume)."""

from src.user_inputs.base import UserInput, UserInputRequest
from src.user_inputs.bounding_box import BoundingBoxRequest, BoundingBoxUserInput
from src.user_inputs.location import (
    LocationCandidate,
    LocationRequest,
    LocationUserInput,
)
from src.user_inputs.router import UserInputRouter
from src.user_inputs.types import InputKind, OSMPrefixType, OSMType, get_osm_type_prefix

# Import concrete kinds so ``UserInput.__init_subclass__`` registers them.
_ = (LocationUserInput, BoundingBoxUserInput)

__all__ = [
    "BoundingBoxRequest",
    "BoundingBoxUserInput",
    "InputKind",
    "LocationCandidate",
    "LocationRequest",
    "LocationUserInput",
    "OSMPrefixType",
    "OSMType",
    "UserInput",
    "UserInputRequest",
    "UserInputRouter",
    "get_osm_type_prefix",
]
