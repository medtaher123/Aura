"""Domain-specific tool planner rules."""

from .disaster_detection import DISASTER_DETECTION_TOOL_RULES, DISASTER_DETECTION_EXAMPLES
from .fire_detection import FIRE_DETECTION_TOOL_RULES, FIRE_DETECTION_EXAMPLES
from .flood_damage import FLOOD_DAMAGE_TOOL_RULES, FLOOD_DAMAGE_EXAMPLES
from .infrastructure import INFRASTRUCTURE_TOOL_RULES, INFRASTRUCTURE_EXAMPLES
from .stac import STAC_EXAMPLES, STAC_TOOL_RULES

DOMAIN_TOOL_RULES: dict[str, tuple[str, ...]] = {
    "flood_damage": FLOOD_DAMAGE_TOOL_RULES,
    "fire_detection": FIRE_DETECTION_TOOL_RULES,
    "disaster_detection": DISASTER_DETECTION_TOOL_RULES,
    "infrastructure": INFRASTRUCTURE_TOOL_RULES,
    "stac": STAC_TOOL_RULES,
}
DOMAIN_TOOL_EXAMPLES: dict[str, tuple[str, ...]] = {
    "flood_damage": FLOOD_DAMAGE_EXAMPLES,
    "fire_detection": FIRE_DETECTION_EXAMPLES,
    "disaster_detection": DISASTER_DETECTION_EXAMPLES,
    "infrastructure": INFRASTRUCTURE_EXAMPLES,
    "stac": STAC_EXAMPLES,
}

__all__ = ["DOMAIN_TOOL_RULES", "DOMAIN_TOOL_EXAMPLES"]
