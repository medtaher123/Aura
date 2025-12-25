from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from src.core.prompts import get_data_agent_react_prompt
from src.tools.tools import get_all_tools
from src.tools.contracts import ToolResponse, make_tool_response


def _infer_required_tools(user_text: str) -> list[str]:
    """Best-effort mapping from user intent to the tools DataAgent should run.

    This prevents planner drift by keeping the loop goal-driven.
    """
    t = (user_text or "").lower()
    required: list[str] = []

    # GeoServer risk masks: if user explicitly asks for GeoServer mask/polygons/WMS/WFS,
    # do NOT call other tools (per DataAgent prompt rules).
    if any(k in t for k in ["geoserver", "risk mask", "mask", "polygon", "polygons", "wms", "wfs"]):
        return ["geoserver_risk_mask_tool"]

    # EO imagery / STAC
    if any(k in t for k in ["satellite", "sentinel", "stac", "imagery", "image", "images", "thumbnail", "thumbnails"]):
        required.append("query_stac_catalog")

    # Fire detection
    if any(k in t for k in ["fire", "fires", "incend", "incendie", "wildfire"]):
        required.append("detect_fire_tool")

    # Disaster events (flood/storm/etc.)
    if any(k in t for k in ["flood", "storm", "earthquake", "drought", "extreme temperature", "disaster", "emdat"]):
        required.append("query_disaster_events_tool")

    # Weather
    if any(k in t for k in ["weather", "meteo", "météo", "forecast"]):
        required.append("weather_tool")

    # Route / itinerary
    if "->" in (user_text or "") or any(k in t for k in ["route", "itinerary", "directions"]):
        required.append("get_route_info")

    # Water ingress
    if any(k in t for k in ["water ingress", "ingress", "surface water", "runoff", "flow accumulation"]):
        required.append("estimate_surface_water_ingress_tool")

    # De-dup preserving order
    seen = set()
    out: list[str] = []
    for x in required:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extract_json_obj(text: str) -> Optional[dict]:
    if not text:
        return None
    candidates: List[str] = []

    # Prefer ```json ... ``` blocks
    for m in re.finditer(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE):
        candidates.append(m.group(1))

    # Fallback: try all minimal {...} candidates (non-greedy)
    for m2 in re.finditer(r"(\{.*?\})", text, flags=re.DOTALL):
        candidates.append(m2.group(1))

    # Try parsing candidates in order
    for blob in candidates:
        try:
            obj = json.loads(blob)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    return None


def _pick_action(plan_text: str) -> Tuple[Optional[str], Optional[str]]:
    obj = _extract_json_obj(plan_text)
    if not isinstance(obj, dict):
        return None, None
    action = obj.get("action")
    action_input = obj.get("action_input")
    if not isinstance(action, str) or not action.strip():
        return None, None

    # Some models may return null/number/object for action_input; coerce to string.
    if action_input is None:
        return action.strip(), ""
    if isinstance(action_input, str):
        return action.strip(), action_input
    return action.strip(), json.dumps(action_input, ensure_ascii=False)


def _invoke_tool_safely(tool: Any, tool_input: Any) -> Any:
    # 0-arg tools
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        try:
            fields = list(args_schema.model_fields.keys())
            if len(fields) == 0:
                return tool.invoke({})
        except Exception:
            pass

    try:
        return tool.invoke(tool_input)
    except Exception:
        pass

    if args_schema is not None:
        try:
            fields = list(args_schema.model_fields.keys())
            if len(fields) == 1:
                # If upstream passed {'input': '...'} but schema expects something else (e.g. 'params'),
                # unwrap the common case.
                if isinstance(tool_input, dict) and len(tool_input) == 1 and "input" in tool_input:
                    tool_input = tool_input.get("input")
                return tool.invoke({fields[0]: tool_input})
        except Exception:
            pass

    args = getattr(tool, "args", None)
    if isinstance(args, dict) and len(args) == 1:
        key = next(iter(args.keys()))
        try:
            return tool.invoke({key: tool_input})
        except Exception:
            pass

    # Last resort: if the tool validates input with a schema, avoid hard-crashing on validation errors.
    try:
        return tool.invoke({"input": tool_input})
    except Exception as e:
        return make_tool_response(
            tool_name=getattr(tool, "name", "tool"),
            message=f"❌ Tool invocation failed: {e}",
            data={"exception": repr(e), "tool_input": str(tool_input)},
            error=True,
        )


def _coerce_tool_response(obj: Any, *, tool_name: str) -> ToolResponse:
    if isinstance(obj, dict) and "message" in obj and "artifacts" in obj and "tool_name" in obj and "error" in obj:
        # Ensure artifacts keys exist
        artifacts = obj.get("artifacts") or {"maps": [], "thumbnails": [], "urls": []}
        if isinstance(artifacts, dict):
            artifacts.setdefault("maps", [])
            artifacts.setdefault("thumbnails", [])
            artifacts.setdefault("urls", [])
        obj["artifacts"] = artifacts
        return obj  # type: ignore[return-value]

    return make_tool_response(
        tool_name=tool_name,
        message=str(obj),
        artifacts={"maps": [], "thumbnails": [], "urls": []},
        data={"raw": str(obj)},
        error=False,
    )


def _merge_steps_into_response(user_text: str, steps: list[ToolResponse], final_message: Optional[str]) -> ToolResponse:
    merged_maps_str: list[str] = []
    merged_maps_other: list[Any] = []
    merged_thumbs: list[str] = []
    merged_urls: list[str] = []

    start_date = end_date = country = city = None
    coordinates = None

    for r in steps:
        artifacts = r.get("artifacts") or {}
        for x in (artifacts.get("maps") or []):
            if isinstance(x, str):
                merged_maps_str.append(x)
            elif isinstance(x, dict):
                merged_maps_other.append(x)
        merged_thumbs.extend([x for x in (artifacts.get("thumbnails") or []) if isinstance(x, str)])
        merged_urls.extend([x for x in (artifacts.get("urls") or []) if isinstance(x, str)])

        start_date = start_date or r.get("start_date")
        end_date = end_date or r.get("end_date")
        country = country or r.get("country")
        city = city or r.get("city")
        coordinates = coordinates or r.get("coordinates")

    # De-dup while preserving order
    def dedup(xs: list[str]) -> list[str]:
        seen = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    merged_maps_str = dedup(merged_maps_str)
    merged_thumbs = dedup(merged_thumbs)
    merged_urls = dedup(merged_urls)

    # Keep legacy string maps first (stable ordering), then structured map specs.
    merged_maps: list[Any] = [*merged_maps_str, *merged_maps_other]

    if isinstance(final_message, str) and final_message.strip():
        message = final_message.strip()
    else:
        # fallback: concatenate tool messages
        message = "\n\n".join([f"{r.get('tool_name')}: {r.get('message')}" for r in steps if r.get("message")])

    return make_tool_response(
        tool_name="data_agent",
        message=message or "No data gathered.",
        artifacts={"maps": merged_maps, "thumbnails": merged_thumbs, "urls": merged_urls},
        start_date=start_date,
        end_date=end_date,
        country=country,
        city=city,
        coordinates=coordinates,
        data={
            "user_query": user_text,
            "tool_calls": [
                {
                    "tool_name": r.get("tool_name"),
                    "error": r.get("error"),
                    "message": r.get("message"),
                    "data": r.get("data"),
                }
                for r in steps
            ],
        },
        error=any(bool(r.get("error")) for r in steps),
    )


@dataclass
class MultiStepDataAgentExecutor:
    graph: Any

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_text = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        context = inputs.get("context") if isinstance(inputs, dict) else None
        result = self.graph.invoke({"input": user_text, "context": context})
        return {"output": result.get("output", result)}


def create_data_agent_executor(max_steps: int = 10) -> MultiStepDataAgentExecutor:
    # DataAgent should focus on data/tools, not chit-chat or utilities.
    excluded = {"general_question_tool", "calculator", "get_date", "get_time"}
    tools = [t for t in get_all_tools() if getattr(t, "name", None) not in excluded]
    tool_map = {t.name: t for t in tools}

    llm = ChatOllama(model="mistral", temperature=0.1)
    prompt = get_data_agent_react_prompt(list(tool_map.keys()))

    graph = StateGraph(dict)

    def plan_node(state: dict) -> dict:
        # IMPORTANT: With a dict-typed StateGraph, returning partial dicts can
        # overwrite state. Always carry forward existing keys.
        next_state = dict(state)

        user_text = next_state.get("input", "") or ""
        context = next_state.get("context") or ""
        steps: list[ToolResponse] = next_state.get("steps", []) or []
        step_count = int(next_state.get("step_count", 0))

        required_tools: list[str] = next_state.get("required_tools") or []
        if not required_tools:
            required_tools = _infer_required_tools(user_text)
        completed_tools: list[str] = next_state.get("completed_tools") or []

        remaining = [t for t in required_tools if t not in completed_tools]

        # Auto-finalize when all required tools ran successfully.
        if steps and not remaining:
            next_state.update({
                "done": True,
                "final_message": "",
                "required_tools": required_tools,
                "completed_tools": completed_tools,
                "step_count": step_count,
            })
            return next_state

        history_lines = []
        for i, r in enumerate(steps[-5:], start=1):
            history_lines.append(
                f"{i}) tool={r.get('tool_name')} error={r.get('error')} message={r.get('message')}"
            )
        history = "\n".join(history_lines) if history_lines else "(none)"

        # If we can, constrain the planner to only pick remaining required tools.
        remaining_hint = ", ".join(remaining) if remaining else "(none)"

        context_block = ""
        if isinstance(context, str) and context.strip():
            context_block = f"Conversation context:\n{context.strip()}\n\n"

        msg = llm.invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(
                    content=(
                        f"{context_block}"
                        f"User request: {user_text}\n"
                        f"Required tools (in order): {', '.join(required_tools) if required_tools else '(none)'}\n"
                        f"Remaining required tools: {remaining_hint}\n\n"
                        f"Previous tool results:\n{history}"
                    )
                ),
            ]
        )

        plan_text = str(msg.content)
        print("\n[DataAgent] plan_raw:", plan_text)
        action, action_input = _pick_action(plan_text)

        if not action:
            # If planning fails after we already gathered data, finalize with fallback summary.
            if steps:
                print("[DataAgent] plan_parse_failed; finalizing with gathered tool results")
                next_state.update({
                    "done": True,
                    "final_message": "",
                    "required_tools": required_tools,
                    "completed_tools": completed_tools,
                    "step_count": step_count,
                })
                return next_state
            # Otherwise ask for rephrase
            print("[DataAgent] plan_parse_failed; no steps; asking for rephrase")
            next_state.update({
                "done": True,
                "final_message": "I couldn't plan the tool calls. Please rephrase your request.",
                "required_tools": required_tools,
                "completed_tools": completed_tools,
                "step_count": step_count,
            })
            return next_state

        if action.upper() == "FINAL":
            next_state.update({
                "done": True,
                "final_message": action_input or "",
                "required_tools": required_tools,
                "completed_tools": completed_tools,
                "step_count": step_count,
            })
            return next_state

        # Enforce remaining required tools if we have them.
        if remaining and action not in remaining:
            print(f"[DataAgent] overriding action='{action}' to remaining_required='{remaining[0]}'")
            action = remaining[0]
            # Use the original user text as tool input unless the planner gave something explicit.
            action_input = action_input or user_text

        # If we're about to call fire detection, feed it a clean, parseable query
        # derived from already-known city + dates (instead of vague 'provided bbox').
        if action == "detect_fire_tool":
            known_city = None
            known_start = None
            known_end = None
            for r in reversed(steps):
                known_city = known_city or r.get("city")
                known_start = known_start or r.get("start_date")
                known_end = known_end or r.get("end_date")
                if known_city and known_start and known_end:
                    break
            if known_city and known_start and known_end:
                action_input = f"fires near {known_city} from {known_start} to {known_end} within 100 km"

        next_state.update({
            "next_tool": action,
            "next_input": action_input,
            "done": False,
            "required_tools": required_tools,
            "completed_tools": completed_tools,
            "step_count": step_count,
        })
        return next_state

    def tool_node(state: dict) -> dict:
        next_state = dict(state)

        user_text = next_state.get("input", "") or ""
        steps: list[ToolResponse] = next_state.get("steps", []) or []
        step_count = int(next_state.get("step_count", 0))
        required_tools: list[str] = next_state.get("required_tools") or []
        completed_tools: list[str] = next_state.get("completed_tools") or []

        tool_name = next_state.get("next_tool")
        tool_input = next_state.get("next_input")

        if tool_input is None or (isinstance(tool_input, str) and not tool_input.strip()):
            tool_input = user_text

        if not isinstance(tool_name, str) or not tool_name:
            next_state.update({"done": True, "final_message": "No tool selected.", "steps": steps})
            return next_state

        tool = tool_map.get(tool_name)
        if tool is None:
            steps.append(
                make_tool_response(
                    tool_name=tool_name,
                    message=f"Tool '{tool_name}' not found.",
                    data={"requested_tool": tool_name},
                    error=True,
                )
            )
        else:
            try:
                raw = _invoke_tool_safely(tool, tool_input)
            except Exception as e:
                raw = make_tool_response(
                    tool_name=tool_name,
                    message=f"❌ Tool '{tool_name}' raised an exception: {e}",
                    data={"exception": repr(e), "tool_input": str(tool_input)},
                    error=True,
                )

            coerced = _coerce_tool_response(raw, tool_name=tool_name)
            print(f"[DataAgent] tool_done tool={tool_name} error={coerced.get('error')}")
            steps.append(coerced)

            # Track completion only for required tools and only if the call succeeded.
            # IMPORTANT: if a required tool fails, don't endlessly retry it.
            # Mark it as completed (attempted) so we can finalize with partial data.
            if tool_name in required_tools and tool_name not in completed_tools:
                completed_tools.append(tool_name)

        step_count += 1
        if step_count >= max_steps:
            next_state.update({
                "done": True,
                # Leave final_message empty so the merger can surface tool messages.
                "final_message": "",
                "steps": steps,
                "step_count": step_count,
                "required_tools": required_tools,
                "completed_tools": completed_tools,
            })
            return next_state

        next_state.update({
            "steps": steps,
            "step_count": step_count,
            "required_tools": required_tools,
            "completed_tools": completed_tools,
        })
        return next_state

    def finalize_node(state: dict) -> dict:
        user_text = state.get("input", "") or ""
        steps: list[ToolResponse] = state.get("steps", []) or []
        final_message = state.get("final_message")
        output = _merge_steps_into_response(user_text, steps, final_message)
        # Preserve the rest of the state for easier debugging.
        next_state = dict(state)
        next_state["output"] = output
        return next_state

    def _route_after_plan(state: dict) -> str:
        return "finalize" if state.get("done") else "tool"

    def _route_after_tool(state: dict) -> str:
        return "finalize" if state.get("done") else "plan"

    graph.add_node("plan", plan_node)
    graph.add_node("tool", tool_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", _route_after_plan, {"tool": "tool", "finalize": "finalize"})
    graph.add_conditional_edges("tool", _route_after_tool, {"plan": "plan", "finalize": "finalize"})
    graph.add_edge("finalize", END)

    return MultiStepDataAgentExecutor(graph=graph.compile())