"""Domain-specific tool planner rules."""

from .disaster_detection import DISASTER_DETECTION_TOOL_RULES
from .fire_detection import FIRE_DETECTION_TOOL_RULES
from .flood_damage import FLOOD_DAMAGE_TOOL_RULES
from .infrastructure import INFRASTRUCTURE_TOOL_RULES
from .stac import STAC_TOOL_RULES

DOMAIN_TOOL_RULES: dict[str, tuple[str, ...]] = {
    "flood_damage": FLOOD_DAMAGE_TOOL_RULES,
    "fire_detection": FIRE_DETECTION_TOOL_RULES,
    "disaster_detection": DISASTER_DETECTION_TOOL_RULES,
    "infrastructure": INFRASTRUCTURE_TOOL_RULES,
    "stac": STAC_TOOL_RULES,
}

__all__ = ["DOMAIN_TOOL_RULES"]
