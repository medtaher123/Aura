"""Flood damage domain node."""

from __future__ import annotations

from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter
from eo_llm.adapters.mcp_client import call_mcp_tool
from eo_llm.graph.state import GraphState, validate_state


def flood_damage_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    selected = set(s.selected_domains)
    if "flood_damage" not in selected:
        return {}

    resolved = s.resolved_location.model_dump(mode="python", exclude_none=True)
    lat = s.resolved_location.lat
    lon = s.resolved_location.lon
    if lat is None or lon is None:
        return {
            "domain_results": {
                "flood_damage": {
                    "status": "skipped",
                    "resolved_location": resolved or {},
                    "message": "Missing resolved lat/lon; flood tools not called.",
                    "error": True,
                }
            }
        }

    display_name = s.resolved_location.display_name or ""
    country_name = display_name.split(",")[-1].strip() if display_name else ""
    runtime_args = {
        "geoserver_risk_mask_tool": {
            "risk_type": "flood",
            "lat": float(lat),
            "lon": float(lon),
            "location": display_name or None,
        },
        "streamflow_forecast_tool": {
            "lat": float(lat),
            "lon": float(lon),
        },
        "estimate_surface_water_ingress_tool": {
            "lat": float(lat),
            "lon": float(lon),
            "location_input": display_name or None,
        },
        "flood_damage_city_tool": {
            "city": display_name or None,
            "depth_m": 1.0,
        },
        "flood_depth_damage_tool": {
            "country": country_name or None,
            "depth_m": 1.0,
        },
    }

    adapter = AgentCoreAdapter()
    try:
        plan = adapter.select_tool_plan(domain="flood_damage", query=s.query)
        execution = adapter.execute_tool_plan(
            plan=plan,
            runtime_args_by_tool=runtime_args,
            tool_caller=call_mcp_tool,
            execution_context={
                "query": s.query,
                "domain": "flood_damage",
                "resolved_location": resolved,
            },
        )
    except Exception as exc:
        return {
            "domain_results": {
                "flood_damage": {
                    "status": "error",
                    "resolved_location": resolved,
                    "message": f"Tool planning/execution failed: {exc}",
                    "summary": {"successful_steps": 0},
                    "error": True,
                }
            }
        }

    successful = [step for step in execution.steps if step.status == "done" and step.result]
    final_step = successful[-1] if successful else None
    return {
        "domain_results": {
            "flood_damage": {
                "status": "done" if execution.summary.successful_steps > 0 else "error",
                "resolved_location": resolved,
                "tool": final_step.tool_name if final_step else None,
                "arguments": final_step.input_arguments if final_step else {},
                "result": final_step.result if final_step else {},
                "plan": plan.model_dump(mode="python"),
                "executions": [step.model_dump(mode="python") for step in execution.steps],
                "summary": execution.summary.model_dump(mode="python"),
            }
        }
    }
