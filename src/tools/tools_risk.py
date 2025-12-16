from datetime import date, datetime
from langchain.tools import tool
# Local package imports (relative to src/tools)
from .tools_stac import query_stac_catalog
from .fire_detection import detect_fire_tool
from .flood_detection import query_disaster_events_tool
from .water_ingress import estimate_surface_water_ingress_tool
from .geographic_info import geo_info_tool
from .itinerary import get_route_info
from .weather import weather_tool
from .general_chat import general_question_tool


@tool
def get_time() -> str:
    """
    Get the current time in a human-readable string format.
    """
    current_time = datetime.now().strftime("%Hh%M")
    # Return a final answer sentence instead of just the raw time string
    return f"The current time is {current_time}."


@tool
def get_date() -> str:
    """
    Get the current date in a human-readable string format.
    """
    #print("Debug: get_date called",date.today())
    current_date = date.today().strftime("%d/%m/%Y")
    #print(f"Debug: current_date = {current_date}")
    return f"Today's date is {current_date}."


@tool
def calculator(expression: str) -> str:
    """
    Evaluate a simple arithmetic expression (e.g., '23 * 7').
    Expected format: 'number operator number'
    """
    try:
        cleaned = expression.strip().replace(" ", "")
        allowed_chars = set("0123456789+-*/.() ")
        if not all(c in allowed_chars for c in cleaned):
            return "Error: Disallowed characters in expression"
        return str(eval(cleaned))
    except Exception:
        return "Error: Invalid arithmetic expression"


def get_all_tools():
    """
    Return the list of all tools available to the agent.
    """
    return [
        get_date,
        get_time,
        calculator,
        query_stac_catalog,
        detect_fire_tool,
        query_disaster_events_tool,
        estimate_surface_water_ingress_tool,
        geo_info_tool,
        get_route_info,
        weather_tool,
        general_question_tool,
    ]