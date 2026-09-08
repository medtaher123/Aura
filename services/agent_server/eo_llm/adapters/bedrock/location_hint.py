"""Schema for geo-location query extraction."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

#TODO: not supposed to be here, should be in the graph/state.py

class LocationHint(BaseModel):
    """Geocodable place extracted from a user query or document."""

    model_config = ConfigDict(extra="forbid")

    place_query: str
