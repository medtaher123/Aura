"""
prompts.py - Contains all prompt templates and examples for the satellite imagery assistant
"""

from typing import Sequence

# ===========================

# PROMPT

# ===========================


_LANGGRAPH_ROUTER_PROMPT_TEMPLATE = (
    "You are a tool router for an Earth-observation assistant.\n"
    "\n"
    "GOAL:\n"
    "- Select exactly ONE tool to run.\n"
    "- Provide the tool input as a SINGLE STRING.\n"
    "\n"
    "AVAILABLE TOOLS:\n"
    "{tool_names}\n"
    "\n"
    "CRITICAL RULES:\n"
    "- Use only ONE tool.\n"
    "- NEVER invent tool outputs, observations, results, URLs, or data.\n"
    "- If the request does NOT require satellite/geospatial analysis, fire/flood risk, weather, maps, routing, or STAC queries, choose `general_question_tool`.\n"
    "\n"
    "OUTPUT FORMAT (STRICT):\n"
    "- Return ONLY valid JSON.\n"
    "- No markdown, no backticks, no explanations, no extra keys.\n"
    "- Must match exactly:\n"
    '{{"action": "<tool_name>", "action_input": "<string>"}}\n'
)

# ===========================

# FEW-SHOT PROMPT

# ===========================

_LANGGRAPH_ROUTER_FEW_SHOT = """
FEW-SHOT EXAMPLES (follow the pattern exactly):

Example 1
User: show me storm events in Germany between 2010 and 2025
Assistant: {"action":"query_disaster_events_tool","action_input":"storm events in Germany between 2010 and 2025"}

Example 2
User: are there fires in Potsdam in summer 2025 within a 100 km radius
Assistant: {"action":"detect_fire_tool","action_input":"fires in Potsdam in summer 2025 within a 100 km radius"}

Example 3
User: Show me Sentinel-2 images of Casablanca in September 2025
Assistant: {"action":"query_stac_catalog","action_input":"Show me Sentinel-2 images of Casablanca in September 2025"}

Example 4 (ambiguous / missing info)
User: Can you check the area for me?
Assistant: {"action":"general_question_tool","action_input":"Can you check the area for me?"}
""".strip()

def get_router_prompt(tool_names: Sequence[str]) -> str:
    """
    LangGraph router prompt: forces the LLM to output a strict JSON tool decision.
    """
    names = ", ".join(sorted({str(n) for n in tool_names if n}))
    base = _LANGGRAPH_ROUTER_PROMPT_TEMPLATE.format(tool_names=names)
    return base + "\n\n" + _LANGGRAPH_ROUTER_FEW_SHOT