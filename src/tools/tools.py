from datetime import date, datetime
from langchain.tools import tool
# Local package imports (relative to src/tools)
from .tools_stac import query_stac_catalog
from .fire_detection import detect_fire_tool
from .disaster_detection import query_disaster_events_tool
from .water_ingress import estimate_surface_water_ingress_tool
from .geographic_info import geo_info_tool
from .itinerary import get_route_info
from .weather import weather_tool
from .general_chat import general_question_tool
from .risk_geoserver import geoserver_risk_mask_tool
from .hazard_detection import query_hazards_tool
from .contracts import make_tool_response


@tool
def get_time() -> dict:
    """
    Get the current time in a human-readable string format.
    """
    current_time = datetime.now().strftime("%Hh%M")
    return make_tool_response(
        tool_name="get_time",
        message=f"The current time is {current_time}.",
        data={"time": current_time},
        error=False,
    )


@tool
def get_date() -> dict:
    """
    Get the current date in a human-readable string format.
    """
    #print("Debug: get_date called",date.today())
    current_date = date.today().strftime("%d/%m/%Y")
    #print(f"Debug: current_date = {current_date}")
    return make_tool_response(
        tool_name="get_date",
        message=f"Today's date is {current_date}.",
        data={"date": current_date},
        error=False,
    )


@tool
def calculator(expression: str) -> dict:
    """
    Evaluate a simple arithmetic expression (e.g., '23 * 7').
    Expected format: 'number operator number'
    """
    try:
        cleaned = expression.strip().replace(" ", "")
        allowed_chars = set("0123456789+-*/.() ")
        if not all(c in allowed_chars for c in cleaned):
            return make_tool_response(
                tool_name="calculator",
                message="Error: Disallowed characters in expression",
                data={"expression": expression},
                error=True,
            )
        result = str(eval(cleaned))
        return make_tool_response(
            tool_name="calculator",
            message=result,
            data={"expression": expression, "result": result},
            error=False,
        )
    except Exception:
        return make_tool_response(
            tool_name="calculator",
            message="Error: Invalid arithmetic expression",
            data={"expression": expression},
            error=True,
        )


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
        query_hazards_tool,
        get_route_info,
        weather_tool,
        geoserver_risk_mask_tool,
    ]