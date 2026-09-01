"""Typed user-input kinds (request / attachment answer / resume)."""

from src.user_inputs.base import UserInput, UserInputRequest
from src.user_inputs.bounding_box import BoundingBoxRequest, BoundingBoxUserInput
from src.user_inputs.location import (
    LocationCandidate,
    LocationRequest,
    LocationUserInput,
)
from src.user_inputs.multiple_choice import (
    MultipleChoiceOption,
    MultipleChoiceRequest,
    MultipleChoiceUserInput,
)
from src.user_inputs.router import UserInputRouter
from src.user_inputs.types import (
    InputKind,
    OTHER_OPTION_ID,
    OSMPrefixType,
    OSMType,
    get_osm_type_prefix,
)

# Import concrete kinds so ``UserInput.__init_subclass__`` registers them.
_ = (LocationUserInput, BoundingBoxUserInput, MultipleChoiceUserInput)

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
