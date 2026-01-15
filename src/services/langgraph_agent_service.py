from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from src.services.llm_service import get_chat_llm
from ..core.prompts import get_router_prompt
from ..tools.tools import get_all_tools
from ..tools.contracts import make_tool_response


def _extract_json_obj(text: str) -> Optional[dict]:
    if not text:
        return None

    # Prefer ```json ... ``` blocks
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    candidates = []
    if m:
        candidates.append(m.group(1))

    # Fallback: first {...} block (best-effort)
    m2 = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if m2:
        candidates.append(m2.group(1))

    for blob in candidates:
        try:
            return json.loads(blob)
        except Exception:
            continue
    return None


def _pick_tool_call(plan_text: str) -> Tuple[Optional[str], Any]:
    obj = _extract_json_obj(plan_text)
    if not isinstance(obj, dict):
        return None, None

    # Preferred strict format
    if isinstance(obj.get("action"), str) and obj.get("action"):
        return obj["action"], obj.get("action_input")

    # Fallback formats you’ve seen
    if isinstance(obj.get("tools"), list) and obj["tools"]:
        tool_name = obj["tools"][0]
        obs = obj.get("observation")
        if isinstance(obs, dict) and obs:
            return tool_name, next(iter(obs.values()))
        return tool_name, obs

    if isinstance(obj.get("tools_used"), list) and obj["tools_used"]:
        tool_name = obj["tools_used"][0]
        obs = obj.get("observation")
        if isinstance(obs, dict) and obs:
            return tool_name, next(iter(obs.values()))
        return tool_name, obs

    # Your latest format: {"Data":[{"tool":"...", "parameters":{...}}]}
    data = obj.get("Data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        tool_name = data[0].get("tool")
        params = data[0].get("parameters")
        if isinstance(tool_name, str) and tool_name:
            return tool_name, params

    return None, None


def _invoke_tool_safely(tool: Any, tool_input: Any) -> Any:
    # 0-arg tools (e.g. get_date/get_time)
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        try:
            fields = list(args_schema.model_fields.keys())
            if len(fields) == 0:
                return tool.invoke({})
        except Exception:
            pass

    # Try plain input first (works for many single-arg tools)
    try:
        return tool.invoke(tool_input)
    except Exception:
        pass

    # Try wrapping into the tool's single expected argument
    if args_schema is not None:
        try:
            fields = list(args_schema.model_fields.keys())
            if len(fields) == 1:
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

    # Final fallback
    return tool.invoke({"input": tool_input})


@dataclass
class LangGraphAgentExecutor:
    graph: Any

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_text = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        result = self.graph.invoke({"input": user_text})
        return {"output": result.get("output", result)}


def create_langgraph_agent_executor() -> LangGraphAgentExecutor:
    tools = get_all_tools()
    tool_map = {t.name: t for t in tools}
    router_prompt = get_router_prompt(list(tool_map.keys()))

    llm = get_chat_llm()

    graph = StateGraph(dict)

    def plan_node(state: dict) -> dict:
        user_text = state.get("input", "")
        msg = llm.invoke(
            [
                SystemMessage(content=router_prompt),
                HumanMessage(content=user_text),
            ]
        )
        return {"plan": msg.content, "input": user_text}

    def tool_node(state: dict) -> dict:
        plan = state.get("plan", "") or ""
        user_text = state.get("input", "") or ""

        tool_name, tool_input = _pick_tool_call(plan)

        if not tool_name:
            tool_name = "general_question_tool"
            tool_input = user_text

        tool = tool_map.get(tool_name)
        if tool is None:
            return {
                "output": make_tool_response(
                    tool_name="langgraph_agent",
                    message=f"Tool '{tool_name}' not found.",
                    data={"plan": plan, "requested_tool": tool_name},
                    error=True,
                )
            }

        # If the planner didn't provide an input, fall back to the user text.
        if tool_input is None:
            tool_input = user_text
        if isinstance(tool_input, str) and not tool_input.strip():
            tool_input = user_text
        tool_result = _invoke_tool_safely(tool, tool_input)
        return {"output": tool_result}

    graph.add_node("plan", plan_node)
    graph.add_node("tool", tool_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "tool")
    graph.add_edge("tool", END)

    return LangGraphAgentExecutor(graph=graph.compile())