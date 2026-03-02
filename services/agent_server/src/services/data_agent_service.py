"""Data Agent Service.

Multi-step ReAct agent for gathering data using MCP tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from ..core.logger import get_logger
from ..core.prompts import get_data_agent_react_prompt
from .llm_service import get_chat_llm
from ..tools.tools import get_all_tools
from ..tools.contracts import ToolArtifacts, ToolResponse

logger = get_logger("data_agent")

# Cap size of tool results in planner prompt to avoid Bedrock "prompt too long" (e.g. 200k limit)
MAX_TOOL_RESULT_MESSAGE_CHARS = 1500
MAX_PREVIOUS_TOOL_RESULTS_CHARS = 8000


def _truncate_for_prompt(s: Any, max_chars: int = MAX_TOOL_RESULT_MESSAGE_CHARS) -> str:
    """Truncate string (or stringify and truncate) for inclusion in LLM prompt."""
    if s is None:
        return ""
    text = str(s) if not isinstance(s, str) else s
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "… [truncated]"


def _extract_json_obj(text: str) -> Optional[dict]:
    if not text:
        return None

    # Robust: scan for JSON objects using JSONDecoder.raw_decode.
    # This handles nested objects without regex and tolerates surrounding text.
    dec = json.JSONDecoder()
    s = str(text)
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        try:
            obj, _end = dec.raw_decode(s[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    return None


def _pick_action(plan_payload: Any) -> Tuple[Optional[str], Any, str]:
    def _normalize_payload(payload: Any) -> Any:
        if isinstance(payload, (dict, list)):
            return payload
        if payload is None:
            return None

        s = str(payload).strip()
        if not s:
            return None

        # Try strict JSON first.
        try:
            return json.loads(s)
        except Exception:
            pass

        # Fall back to Python literal evaluation for repr-style lists/dicts.
        try:
            import ast

            return ast.literal_eval(s)
        except Exception:
            pass

        # Last resort: extract the first JSON object embedded in the text.
        return _extract_json_obj(s)

    payload = _normalize_payload(plan_payload)

    # Anthropic tool-use format: list of content blocks or a single dict.
    def _from_tool_use(obj: Any) -> Tuple[Optional[str], Any, str]:
        if not isinstance(obj, dict):
            return None, None, ""
        if obj.get("type") != "tool_use":
            return None, None, ""
        name = obj.get("name")
        tool_input = obj.get("input")
        if not isinstance(name, str) or not name.strip():
            return None, None, ""
        return name.strip(), tool_input, ""

    if isinstance(payload, list):
        for item in payload:
            action, action_input, commentary = _from_tool_use(item)
            if action:
                return action, action_input, commentary
        # If list contains dicts with action schema, use the first one.
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("action"), str):
                payload = item
                break

    # Standard JSON action schema.
    if isinstance(payload, dict):
        action = payload.get("action")
        action_input = payload.get("action_input")
        commentary = payload.get("commentary")
        if isinstance(action, str) and action.strip():
            if not isinstance(commentary, str):
                commentary = ""
            commentary = commentary.strip()

            # Preserve dict/list inputs so tools with structured args can be called directly.
            # If it's null, keep it as empty string for backward compatibility.
            if action_input is None:
                return action.strip(), "", commentary
            return action.strip(), action_input, commentary

        # Tool-use dict fallback.
        action, action_input, commentary = _from_tool_use(payload)
        if action:
            return action, action_input, commentary

    return None, None, ""


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

    # If upstream passes a tuple/list, map it positionally to the schema fields.
    if args_schema is not None and isinstance(tool_input, (tuple, list)):
        try:
            fields = list(args_schema.model_fields.keys())
            if len(fields) == len(tool_input):
                return tool.invoke(
                    {fields[i]: tool_input[i] for i in range(len(fields))}
                )
        except Exception:
            pass

    first_error: Exception | None = None
    try:
        return tool.invoke(tool_input)
    except Exception as e:
        logger.error(
            f"DataAgent tool invocation failed when invoking tool: {tool.name}"
        )
        logger.error(f"     Tool input: {json.dumps(tool_input, indent=2)}")
        logger.error(f"     Exception: {e}")
        first_error = e

    if args_schema is not None:
        try:
            fields = list(args_schema.model_fields.keys())
            if len(fields) == 1:
                # If upstream passed {'input': '...'} but schema expects something else (e.g. 'params'),
                # unwrap the common case.
                if (
                    isinstance(tool_input, dict)
                    and len(tool_input) == 1
                    and "input" in tool_input
                ):
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
    tool_name = getattr(tool, "name", "tool")

    if args_schema is not None:
        try:
            fields = list(args_schema.model_fields.keys())
        except Exception:
            fields = []

        # For structured tools (2+ fields), wrapping under {'input': ...} makes validation worse.
        # Instead, surface a clear error and show expected keys.
        if len(fields) > 1:
            logger.error("DataAgent tool invocation failed when validating input:")
            logger.error(f"     Tool: {tool.name}")
            logger.error(f"     Tool input: {json.dumps(tool_input, indent=2)}")
            logger.error(f"     Exception: {first_error}")
            logger.error(f"     Expected a JSON object with keys: {fields}")
            return ToolResponse(
                tool_name=tool_name,
                message=(
                    f"❌ Tool invocation failed: {first_error or 'invalid input'}\n"
                    f"Expected a JSON object with keys: {fields}"
                ),
                data={
                    "exception": repr(first_error) if first_error else None,
                    "tool_input": tool_input,
                },
                error=True,
            )

    try:
        return tool.invoke({"input": tool_input})
    except Exception as e:
        logger.error(
            f"DataAgent tool invocation failed when trying to invoke tool: {tool.name}"
        )
        logger.error(f"     Tool: {tool.name}")
        logger.error(f"     Tool input: {json.dumps(tool_input, indent=2)}")
        logger.error(f"     Exception: {e}")
        return ToolResponse(
            tool_name=tool_name,
            message=f"❌ Tool invocation failed: {e}",
            data={"exception": repr(e), "tool_input": str(tool_input)},
            error=True,
        )


def _coerce_tool_response(obj: Any, *, tool_name: str) -> ToolResponse:
    if isinstance(obj, ToolResponse):
        return obj

    resp = ToolResponse(
        tool_name=tool_name,
        message=str(obj),
        data={"raw": str(obj)},
        error=False,
    )
    if isinstance(obj, dict):
        if "artifacts" in obj:
            resp.artifacts.maps = obj["artifacts"].get("maps", [])
            resp.artifacts.thumbnails = obj["artifacts"].get("thumbnails", [])
            resp.artifacts.urls = obj["artifacts"].get("urls", [])

        if "message" in obj:
            resp.message = obj["message"]
        if "tool_name" in obj:
            resp.tool_name = obj["tool_name"]
        if "data" in obj:
            resp.data = obj["data"]
        if "error" in obj:
            resp.error = obj["error"]
        if "start_date" in obj:
            resp.start_date = obj["start_date"]
        if "end_date" in obj:
            resp.end_date = obj["end_date"]
        if "country" in obj:
            resp.country = obj["country"]
        if "city" in obj:
            resp.city = obj["city"]
        if "coordinates" in obj:
            resp.coordinates = obj["coordinates"]

    return resp


def _merge_steps_into_response(
    user_text: str, steps: list[ToolResponse], final_message: Optional[str]
) -> ToolResponse:
    logger.info(
        f"Merging steps into response - user_text: {user_text}, steps: {steps}, final_message: {final_message}"
    )
    merged_maps_str: list[str] = []
    merged_maps_other: list[Any] = []
    merged_thumbs: list[str] = []
    merged_urls: list[str] = []

    start_date = end_date = country = city = None
    coordinates = None
    logger.debug("Merging steps into response")

    for r in steps:
        artifacts = r.artifacts
        for x in artifacts.maps:
            if isinstance(x, str):
                merged_maps_str.append(x)
            elif isinstance(x, dict):
                merged_maps_other.append(x)
        merged_thumbs.extend([x for x in (artifacts.thumbnails) if isinstance(x, str)])
        merged_urls.extend([x for x in (artifacts.urls) if isinstance(x, str)])

        start_date = start_date or r.start_date
        end_date = end_date or r.end_date
        country = country or r.country
        city = city or r.city
        coordinates = coordinates or r.coordinates

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

    # If multiple tools produced Pydeck/deck.gl-style map specs, combine them into a
    # single map by concatenating their layers.
    def _is_pydeck_spec(x: Any) -> bool:
        return isinstance(x, dict) and (
            isinstance(x.get("layers"), list) or isinstance(x.get("points"), list)
        )

    pydeck_specs: list[dict] = [m for m in merged_maps_other if _is_pydeck_spec(m)]
    non_pydeck_specs: list[Any] = [
        m for m in merged_maps_other if not _is_pydeck_spec(m)
    ]

    def _layers_from_spec(spec: dict) -> list[dict]:
        layers: list[dict] = []
        layer_specs = spec.get("layers")
        if isinstance(layer_specs, list):
            layers.extend([x for x in layer_specs if isinstance(x, dict)])

        points = spec.get("points")
        if isinstance(points, list):
            # Convert shorthand into an explicit ScatterplotLayer spec.
            layers.append(
                {
                    "type": "ScatterplotLayer",
                    "data": points,
                    "get_position": spec.get("get_position", "[lon, lat]"),
                    "get_radius": spec.get("radius", 50),
                    "radius_units": spec.get("radius_units", "meters"),
                    "radius_min_pixels": spec.get("radius_min_pixels", 3),
                    "radius_max_pixels": spec.get("radius_max_pixels", 15),
                    "get_fill_color": spec.get("fill_color", [255, 0, 0, 160]),
                    "pickable": bool(spec.get("pickable", True)),
                }
            )
        return layers

    combined_specs: list[Any] = []
    if len(pydeck_specs) >= 2:
        base = dict(pydeck_specs[0])
        combined_layers: list[dict] = []
        titles: list[str] = []

        # Prefer the first non-empty tooltip.
        tooltip = base.get("tooltip") if isinstance(base.get("tooltip"), dict) else None

        for spec in pydeck_specs:
            combined_layers.extend(_layers_from_spec(spec))

            title = spec.get("title")
            if isinstance(title, str) and title.strip():
                titles.append(title.strip())

            if tooltip is None and isinstance(spec.get("tooltip"), dict):
                tooltip = spec.get("tooltip")

        # De-dup titles while preserving order
        seen_titles = set()
        titles = [t for t in titles if not (t in seen_titles or seen_titles.add(t))]
        if titles:
            base["title"] = " + ".join(titles)

        if tooltip is not None:
            base["tooltip"] = tooltip

        # Normalize to generic layers form after merge.
        base.pop("points", None)
        base.pop("fill_color", None)
        base.pop("radius", None)
        base.pop("radius_units", None)
        base.pop("radius_min_pixels", None)
        base.pop("radius_max_pixels", None)
        base.pop("get_position", None)
        base["layers"] = combined_layers

        combined_specs.append(base)
    elif len(pydeck_specs) == 1:
        combined_specs.append(pydeck_specs[0])

    combined_specs.extend(non_pydeck_specs)

    # Keep legacy string maps first (stable ordering), then the combined structured map spec(s).
    merged_maps: list[Any] = [*merged_maps_str, *combined_specs]

    if isinstance(final_message, str) and final_message.strip():
        message = final_message.strip()
    else:
        # fallback: concatenate tool messages
        message = "\n\n".join(
            [f"{r.tool_name}: {r.message}" for r in steps if r.message]
        )

    # Overall error semantics: the DataAgent may try multiple tools (or retry the
    # same tool with refined inputs). If at least one tool call succeeded, we
    # should not mark the entire response as an error; the UI can still show
    # per-step failures via `data.tool_calls`.
    overall_error = False
    if steps:
        overall_error = all(bool(r.error) for r in steps)

    return ToolResponse(
        tool_name="data_agent",
        message=message or "No data gathered.",
        artifacts=ToolArtifacts(
            maps=merged_maps, thumbnails=merged_thumbs, urls=merged_urls
        ),
        start_date=start_date,
        end_date=end_date,
        country=country,
        city=city,
        coordinates=coordinates,
        data={
            "user_query": user_text,
            "tool_calls": [
                {
                    "tool_name": r.tool_name,
                    "error": r.error,
                    "message": r.message,
                    "data": r.data,
                }
                for r in steps
            ],
        },
        error=overall_error,
    )


def _tool_call_signature(tool_name: str, tool_input: Any) -> str:
    """Stable signature for de-duplicating identical tool calls."""
    try:
        payload = json.dumps(
            tool_input, sort_keys=True, ensure_ascii=False, default=str
        )
    except Exception:
        payload = str(tool_input)
    return f"{tool_name}::{payload}"


@dataclass
class MultiStepDataAgentExecutor:
    """Multi-step data agent executor using LangGraph."""

    graph: Any

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(inputs, dict) and isinstance(inputs.get("resume_state"), dict):
            # Resume from a previously paused state (e.g., location confirmation).
            state = dict(inputs["resume_state"])
            stream_callback = inputs.get("stream_callback")
            logger.info(
                f"DataAgent resuming - confirmed_locations in state: {state.get('confirmed_locations', {})}"
            )
            if stream_callback is not None:
                state["stream_callback"] = stream_callback
            result = self.graph.invoke(state)
            return {"output": result.get("output", result)}

        user_text = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        context = inputs.get("context") if isinstance(inputs, dict) else None
        stream_callback = (
            inputs.get("stream_callback") if isinstance(inputs, dict) else None
        )
        result = self.graph.invoke(
            {"input": user_text, "context": context, "stream_callback": stream_callback}
        )
        return {"output": result.get("output", result)}


def create_data_agent_executor(
    max_steps: int = 10,
    *,
    llm: Any | None = None,
    tools: list[Any] | None = None,
) -> MultiStepDataAgentExecutor:
    """Create a MultiStepDataAgentExecutor instance."""
    # DataAgent should focus on data/tools, not chit-chat or utilities.
    excluded = {"general_question_tool", "calculator", "get_date", "get_time"}
    if tools is None:
        tools = [t for t in get_all_tools() if getattr(t, "name", None) not in excluded]
    else:
        tools = [t for t in tools if getattr(t, "name", None) not in excluded]

    tool_map = {t.name: t for t in tools}

    if llm is None:
        llm = get_chat_llm()
    prompt = get_data_agent_react_prompt(list(tool_map.keys()))

    graph = StateGraph(dict)  # type: ignore[arg-type]

    def _norm_key(s: str) -> str:
        return " ".join(str(s).strip().lower().split())

    def _apply_confirmed_locations(obj: Any, confirmed: dict[str, str]) -> Any:
        logger.debug(
            f"DataAgent _apply_confirmed_locations: obj={obj}, confirmed={confirmed}"
        )
        if not confirmed:
            return obj
        if isinstance(obj, str):
            if obj.startswith("@"):
                return obj
            k = _norm_key(obj)
            if k in confirmed:
                return confirmed[k]
            # Partial match: "paris" should match the confirmed key
            # "paris, île-de-france, france métropolitaine, france".
            for conf_key, conf_val in confirmed.items():
                if conf_key.startswith(k + ",") or conf_key.startswith(k + " "):
                    return conf_val
            return obj
        if isinstance(obj, list):
            return [_apply_confirmed_locations(x, confirmed) for x in obj]
        if isinstance(obj, dict):
            return {k: _apply_confirmed_locations(v, confirmed) for k, v in obj.items()}
        return obj

    def plan_node(state: dict) -> dict:
        # IMPORTANT: With a dict-typed StateGraph, returning partial dicts can
        # overwrite state. Always carry forward existing keys.
        next_state = dict(state)

        # Resume path: when we paused on a tool call (e.g. ambiguous geocoding),
        # we want to jump straight back to the tool without calling the planner LLM.
        if next_state.get("resume_from_pause") and isinstance(
            next_state.get("next_tool"), str
        ):
            next_state["resume_from_pause"] = False
            next_state["done"] = False
            return next_state

        user_text = next_state.get("input", "") or ""
        context = next_state.get("context") or ""
        steps: list[ToolResponse] = next_state.get("steps", []) or []
        step_count = int(next_state.get("step_count", 0))

        confirmed_locations = next_state.get("confirmed_locations")
        logger.debug(
            f"DataAgent confirmed locations at plan node: {confirmed_locations}"
        )
        if not isinstance(confirmed_locations, dict):
            confirmed_locations = {}
        # Normalize keys once.
        confirmed_locations_norm: dict[str, str] = {}
        for k, v in confirmed_locations.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                normalized_key = _norm_key(k)
                confirmed_locations_norm[normalized_key] = v
                logger.debug(
                    f"DataAgent normalized location key: '{k}' -> '{normalized_key}' = '{v}'"
                )

        if confirmed_locations_norm:
            logger.info(
                f"DataAgent has {len(confirmed_locations_norm)} confirmed locations: {list(confirmed_locations_norm.keys())}"
            )

        required_tools: list[str] = next_state.get("required_tools") or []
        completed_tools: list[str] = next_state.get("completed_tools") or []

        remaining = [t for t in required_tools if t not in completed_tools]

        # Auto-finalize when all required tools ran successfully.
        # IMPORTANT: only do this if required_tools was explicitly provided.
        if steps and required_tools and not remaining:
            next_state.update(
                {
                    "done": True,
                    "final_message": "",
                    "required_tools": required_tools,
                    "completed_tools": completed_tools,
                    "step_count": step_count,
                }
            )
            return next_state

        history_lines = []
        for i, r in enumerate(steps[-5:], start=1):
            tool_input = None
            if isinstance(r.data, dict):
                tool_input = r.data.get("tool_input")
            msg_part = _truncate_for_prompt(r.message)
            input_part = _truncate_for_prompt(tool_input, max_chars=400)
            history_lines.append(
                f"{i}) tool={r.tool_name} error={r.error} input={input_part} message={msg_part}"
            )
        history = "\n".join(history_lines) if history_lines else "(none)"
        if len(history) > MAX_PREVIOUS_TOOL_RESULTS_CHARS:
            history = history[-MAX_PREVIOUS_TOOL_RESULTS_CHARS:].lstrip()
            if "\n" in history[:100]:
                history = history[history.find("\n") + 1 :]
            history = "(earlier results truncated)\n" + history

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

        plan_payload = msg.content
        logger.debug(f"DataAgent plan payload: {json.dumps(plan_payload, indent=2)}")
        action, action_input, commentary = _pick_action(plan_payload)
        logger.debug(
            f"DataAgent plan parsed - action={action}, action_input={action_input}, commentary={commentary}, step_count={step_count}/{max_steps}"
        )

        # If we already confirmed ambiguous locations earlier in this run, apply the
        # same resolution to future tool inputs to avoid re-triggering confirmation.
        if confirmed_locations_norm:
            original_input = action_input
            action_input = _apply_confirmed_locations(
                action_input, confirmed_locations_norm
            )
            if action_input != original_input:
                logger.info(
                    f"DataAgent applied confirmed location substitution: {original_input} -> {action_input}"
                )
            else:
                logger.debug(
                    f"DataAgent location substitution: no match found for input {action_input}"
                )

        if not action:
            # If planning fails after we already gathered data, finalize with fallback summary.
            if steps:
                logger.warning(
                    f"DataAgent plan parsing failed after {len(steps)} successful steps, finalizing with gathered results"
                )
                next_state.update(
                    {
                        "done": True,
                        "final_message": "",
                        "required_tools": required_tools,
                        "completed_tools": completed_tools,
                        "step_count": step_count,
                    }
                )
                return next_state
            # Otherwise ask for rephrase
            logger.warning(
                f"DataAgent plan parsing failed with no prior steps, requesting user to rephrase - user_text: {user_text[:100]}"
            )
            next_state.update(
                {
                    "done": True,
                    "final_message": "I couldn't plan the tool calls. Please rephrase your request.",
                    "required_tools": required_tools,
                    "completed_tools": completed_tools,
                    "step_count": step_count,
                }
            )
            return next_state

        if action.upper() == "FINAL":
            # If required tools remain, do not accept FINAL yet.
            if remaining:
                logger.info(
                    f"DataAgent planner returned FINAL but {len(remaining)} required tools remaining: {remaining}, forcing continuation"
                )
                next_state.update(
                    {
                        "next_tool": remaining[0],
                        "next_input": user_text,
                        "next_commentary": "",
                        "done": False,
                        "required_tools": required_tools,
                        "completed_tools": completed_tools,
                        "step_count": step_count,
                    }
                )
                return next_state
            next_state.update(
                {
                    "done": True,
                    "final_message": action_input or "",
                    "next_commentary": "",
                    "required_tools": required_tools,
                    "completed_tools": completed_tools,
                    "step_count": step_count,
                }
            )
            return next_state

        # Enforce remaining required tools if we have them.
        if remaining and action not in remaining:
            logger.info(
                f"DataAgent overriding planned action '{action}' to next required tool '{remaining[0]}' (remaining: {remaining})"
            )
            action = remaining[0]
            # Use the original user text as tool input unless the planner gave something explicit.
            action_input = action_input or user_text

        next_state.update(
            {
                "next_tool": action,
                "next_input": action_input,
                "next_commentary": commentary,
                "done": False,
                "required_tools": required_tools,
                "completed_tools": completed_tools,
                "step_count": step_count,
            }
        )
        return next_state

    def tool_node(state: dict) -> dict:
        next_state = dict(state)

        user_text = next_state.get("input", "") or ""
        steps: list[ToolResponse] = next_state.get("steps", []) or []
        step_count = int(next_state.get("step_count", 0))
        required_tools: list[str] = next_state.get("required_tools") or []
        completed_tools: list[str] = next_state.get("completed_tools") or []

        executed_sigs: list[str] = next_state.get("executed_tool_call_sigs") or []
        executed_sig_set = set(executed_sigs)

        tool_name = next_state.get("next_tool")
        tool_input = next_state.get("next_input")
        planner_commentary = next_state.get("next_commentary")
        stream_callback = next_state.get("stream_callback")

        if not isinstance(planner_commentary, str):
            planner_commentary = ""
        planner_commentary = planner_commentary.strip()

        if tool_input is None or (
            isinstance(tool_input, str) and not tool_input.strip()
        ):
            tool_input = user_text

        if not isinstance(tool_name, str) or not tool_name:
            next_state.update(
                {"done": True, "final_message": "No tool selected.", "steps": steps}
            )
            return next_state

        tool = tool_map.get(tool_name)
        logger.debug(f"DataAgent calling tool: {tool_name} with input: {tool_input}")
        # De-duplicate exact same tool call (tool + args). This prevents loops where the
        # planner keeps repeating the same step instead of returning FINAL.
        sig = _tool_call_signature(tool_name, tool_input)

        if sig in executed_sig_set and steps:
            logger.info(
                f"DataAgent skipped duplicate tool call: tool={tool_name}, already executed {len(executed_sigs)} unique calls"
            )
            next_state.update(
                {
                    "done": True,
                    "final_message": "",
                    "steps": steps,
                    "step_count": step_count,
                    "required_tools": required_tools,
                    "completed_tools": completed_tools,
                    "executed_tool_call_sigs": executed_sigs,
                }
            )
            return next_state
        if tool is None:
            steps.append(
                ToolResponse(
                    tool_name=tool_name,
                    message=f"Tool '{tool_name}' not found.",
                    data={"requested_tool": tool_name},
                    error=True,
                )
            )
        else:
            if callable(stream_callback):
                try:
                    stream_callback(
                        {
                            "type": "data_agent_step",
                            "phase": "running",
                            "tool_name": tool_name,
                            "commentary": planner_commentary,
                            "tool_input": tool_input,
                        }
                    )
                except Exception:
                    pass
            try:
                raw = _invoke_tool_safely(tool, tool_input)
            except Exception as e:
                raw = ToolResponse(
                    tool_name=tool_name,
                    message=f"❌ Tool '{tool_name}' raised an exception: {e}",
                    data={"exception": repr(e), "tool_input": str(tool_input)},
                    error=True,
                )

            coerced: ToolResponse = _coerce_tool_response(raw, tool_name=tool_name)
            # Attach safe trace metadata for UI/debugging (do not rely on this for tool correctness).
            meta = coerced.data if coerced.data else {}
            if meta.get("tool_input") is None:
                meta["tool_input"] = tool_input
            if meta.get("commentary") is None:
                meta["commentary"] = planner_commentary
            coerced.data = meta

            # Pause point: let the UI ask the user to disambiguate the location,
            # then resume from this exact tool call (without re-running prior steps).
            if bool(meta.get("needs_location_confirmation")) is True:
                logger.info(
                    f"DataAgent tool requires location confirmation: tool={tool_name}, step={step_count + 1}/{max_steps}"
                )
                paused_state = dict(next_state)
                paused_state.pop("stream_callback", None)  # not serializable
                paused_state.pop("output", None)
                paused_state.pop("pause", None)
                paused_state["done"] = False
                paused_state["final_message"] = ""
                paused_state["resume_from_pause"] = True

                resume_patch = (
                    meta.get("resume_patch") if isinstance(meta, dict) else None
                )
                pause_payload = {
                    "resume_state": paused_state,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                }
                if isinstance(resume_patch, dict):
                    pause_payload["resume_patch"] = resume_patch

                next_state["pause"] = {"tool_response": coerced, "pause": pause_payload}
                next_state["done"] = True
                next_state["final_message"] = ""

                if callable(stream_callback):
                    logger.info(
                        "Streaming data agent finalizing with message: Waiting for location confirmation…"
                    )
                    try:
                        stream_callback(
                            {
                                "type": "data_agent_finalizing",
                                "message": "Waiting for location confirmation…",
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error streaming data agent finalizing: {e}")
                        pass
                return next_state

            logger.info(
                f"DataAgent tool completed: tool={tool_name}, error={coerced.error}, step={step_count + 1}/{max_steps}"
            )
            steps.append(coerced)

            if sig not in executed_sig_set:
                executed_sigs.append(sig)
                executed_sig_set.add(sig)

            if callable(stream_callback):
                try:
                    stream_callback(
                        {
                            "type": "data_agent_step",
                            "phase": "done",
                            "tool_name": tool_name,
                            "commentary": planner_commentary,
                            "tool_input": tool_input,
                            "observation": coerced.message,
                            "error": coerced.error,
                        }
                    )
                except Exception:
                    pass

            # Track completion only for required tools and only if the call succeeded.
            # IMPORTANT: if a required tool fails, don't endlessly retry it.
            # Mark it as completed (attempted) so we can finalize with partial data.
            if tool_name in required_tools and tool_name not in completed_tools:
                completed_tools.append(tool_name)

        step_count += 1
        if step_count >= max_steps:
            next_state.update(
                {
                    "done": True,
                    # Leave final_message empty so the merger can surface tool messages.
                    "final_message": "",
                    "steps": steps,
                    "step_count": step_count,
                    "required_tools": required_tools,
                    "completed_tools": completed_tools,
                    "executed_tool_call_sigs": executed_sigs,
                }
            )
            return next_state

        next_state.update(
            {
                "steps": steps,
                "step_count": step_count,
                "required_tools": required_tools,
                "completed_tools": completed_tools,
                "executed_tool_call_sigs": executed_sigs,
            }
        )
        return next_state

    def finalize_node(state: dict) -> dict:
        logger.info(f"DataAgent finalizing - finalize_node state: {state}")
        # If the agent paused (e.g. location confirmation), return that tool response
        # directly (do not merge as final answer), and attach a resumable state blob.
        pause = state.get("pause", {})
        if isinstance(pause.get("pause"), dict):
            tool_resp: ToolResponse = pause.get("tool_response")
            tool_resp.data["pause"] = pause["pause"]
            next_state = dict(state)
            next_state["output"] = tool_resp
            return next_state

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
    graph.add_conditional_edges(
        "plan", _route_after_plan, {"tool": "tool", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "tool", _route_after_tool, {"plan": "plan", "finalize": "finalize"}
    )
    graph.add_edge("finalize", END)

    return MultiStepDataAgentExecutor(graph=graph.compile())
