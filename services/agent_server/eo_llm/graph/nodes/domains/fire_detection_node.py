"""Fire detection domain node."""

from __future__ import annotations

from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter
from eo_llm.adapters.mcp_client import call_mcp_tool
from eo_llm.graph.state import GraphState, validate_state


def fire_detection_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    selected = set(s.selected_domains)
    if "fire_detection" not in selected:
        return {}

    resolved = s.resolved_location.model_dump(mode="python", exclude_none=True)
    lat = s.resolved_location.lat
    lon = s.resolved_location.lon
    if lat is None or lon is None:
        return {
            "domain_results": {
                "fire_detection": {
                    "status": "skipped",
                    "resolved_location": resolved or {},
                    "message": "Missing resolved lat/lon; fire tool not called.",
                    "error": True,
                }
            }
        }

    runtime_args = {
        "detect_fire_tool": {
            "lat": float(lat),
            "lon": float(lon),
            "location": s.resolved_location.display_name or None,
        },
        "clms_burnt_area_impact_tool": {
            "lat": float(lat),
            "lon": float(lon),
            "location": s.resolved_location.display_name or None,
        },
    }
    adapter = AgentCoreAdapter()
    try:
        plan = adapter.select_tool_plan(domain="fire_detection", query=s.query)
        execution = adapter.execute_tool_plan(
            plan=plan,
            runtime_args_by_tool=runtime_args,
            tool_caller=call_mcp_tool,
            execution_context={
                "query": s.query,
                "domain": "fire_detection",
                "resolved_location": resolved,
            },
        )
    except Exception as exc:
        return {
            "domain_results": {
                "fire_detection": {
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
            "fire_detection": {
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
