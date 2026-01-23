from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from src.services.llm_service import get_chat_llm

from src.core.prompts import get_orchestrator_prompt
from src.core.memory import format_chat_history
from src.tools import ToolResponse, make_tool_response
from src.services.data_agent_service import create_data_agent_executor
from src.services.analysis_agent_service import create_analysis_agent_executor


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None

    s = str(text)

    # Prefer ```json ... ``` blocks if present
    m = re.search(r"```json\s*(\{.*?\})\s*```", s, flags=re.DOTALL | re.IGNORECASE)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    # Robust fallback: scan for the first JSON object
    dec = json.JSONDecoder()
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


@dataclass
class OrchestratorExecutor:
    planner_llm: Any
    data_agent: Any
    analysis_agent: Any

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_text = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        chat_history = inputs.get("chat_history") if isinstance(inputs, dict) else None
        stream_callback = (
            inputs.get("stream_callback") if isinstance(inputs, dict) else None
        )
        history_text = format_chat_history(
            chat_history, max_messages=12, max_chars=6000
        )

        # Resume path: continue from a paused DataAgent state without replanning.
        resume = inputs.get("resume") if isinstance(inputs, dict) else None
        if isinstance(resume, dict) and isinstance(resume.get("resume_state"), dict):
            resume_state = resume.get("resume_state")
            orchestrator_trace = (
                resume.get("orchestrator_trace")
                if isinstance(resume.get("orchestrator_trace"), dict)
                else {}
            )
            needs_analysis = bool(
                resume.get("needs_analysis") or orchestrator_trace.get("needs_analysis")
            )
            analysis_goal = (
                resume.get("analysis_goal")
                or orchestrator_trace.get("analysis_goal")
                or ""
            )
            original_user_text = resume.get("user_text") or user_text

            if callable(stream_callback):
                try:
                    stream_callback(
                        {
                            "type": "stage",
                            "stage": "data_agent",
                            "message": "Resuming DataAgent…",
                        }
                    )
                except Exception:
                    pass

            raw = self.data_agent.invoke(
                {"resume_state": resume_state, "stream_callback": stream_callback}
            )
            data_response = (
                raw.get("output", raw)
                if isinstance(raw, dict)
                else make_tool_response(
                    tool_name="data_agent",
                    message=str(raw),
                    error=False,
                )
            )

            # If we paused again (multiple ambiguous locations), return immediately.
            if isinstance(data_response, dict):
                data_data = (
                    data_response.get("data")
                    if isinstance(data_response.get("data"), dict)
                    else {}
                )
                if bool(data_data.get("needs_location_confirmation")) is True:
                    pause = (
                        data_data.get("pause")
                        if isinstance(data_data.get("pause"), dict)
                        else {}
                    )
                    data_response["data"] = {
                        **dict(data_data),
                        "orchestrator_trace": orchestrator_trace,
                        "pause": {
                            **dict(pause),
                            "orchestrator_trace": orchestrator_trace,
                            "needs_analysis": needs_analysis,
                            "analysis_goal": analysis_goal,
                            "user_text": original_user_text,
                        },
                    }
                    return {"output": data_response}

            # AnalysisAgent (optional) after data completes.
            if needs_analysis:
                if callable(stream_callback):
                    try:
                        stream_callback(
                            {
                                "type": "stage",
                                "stage": "analysis_agent",
                                "message": "Writing analysis based on gathered data…",
                            }
                        )
                    except Exception:
                        pass
                analysis_raw = self.analysis_agent.invoke(
                    {
                        "user_question": f"{original_user_text}\n\nAnalysis goal: {analysis_goal}".strip(),
                        "data_response": data_response,
                        "context": history_text,
                        "stream_callback": stream_callback,
                    }
                )
                analysis_resp = (
                    analysis_raw.get("output", analysis_raw)
                    if isinstance(analysis_raw, dict)
                    else make_tool_response(
                        tool_name="analysis_agent",
                        message=str(analysis_raw),
                        error=False,
                    )
                )

                if isinstance(analysis_resp, dict):
                    analysis_data = (
                        analysis_resp.get("data")
                        if isinstance(analysis_resp.get("data"), dict)
                        else {}
                    )
                    analysis_resp["data"] = {
                        **dict(analysis_data),
                        "orchestrator_trace": orchestrator_trace,
                    }
                return {"output": analysis_resp}

            if isinstance(data_response, dict):
                data_data = (
                    data_response.get("data")
                    if isinstance(data_response.get("data"), dict)
                    else {}
                )
                data_response["data"] = {
                    **dict(data_data),
                    "orchestrator_trace": orchestrator_trace,
                }
            return {"output": data_response}

        augmented_user_text = user_text
        if history_text:
            augmented_user_text = (
                "Conversation so far (most recent last):\n"
                f"{history_text}\n\n"
                f"User request: {user_text}"
            )

        # 1) Plan
        plan_prompt = get_orchestrator_prompt()
        plan_msg = self.planner_llm.invoke(
            [
                SystemMessage(content=plan_prompt),
                HumanMessage(content=augmented_user_text),
            ]
        )
        plan = _extract_json(str(plan_msg.content)) or {}
        if not plan:
            # Retry once with a stricter instruction when the model ignores JSON output.
            retry_msg = self.planner_llm.invoke(
                [
                    SystemMessage(
                        content=(
                            plan_prompt
                            + "\n\nIMPORTANT: Return ONLY valid JSON with the exact keys. "
                            + "Do NOT answer the user question."
                        )
                    ),
                    HumanMessage(content=augmented_user_text),
                ]
            )
            plan = _extract_json(str(retry_msg.content)) or {}

        # Heuristic fallback if still empty: detect data/analysis needs from keywords.
        if not plan:
            lower = user_text.lower()
            data_keywords = (
                "storm",
                "disaster",
                "earthquake",
                "flood",
                "fire",
                "weather",
                "temperature",
                "drought",
                "risk",
                "mask",
                "satellite",
                "image",
                "imagery",
                "map",
                "route",
                "itinerary",
            )
            analysis_keywords = (
                "analyze",
                "analysis",
                "summarize",
                "report",
                "assess",
                "explain results",
                "findings",
            )
            needs_data = any(k in lower for k in data_keywords)
            needs_analysis = any(k in lower for k in analysis_keywords)
            plan = {
                "needs_data": needs_data,
                "needs_analysis": needs_analysis,
                "data_query": user_text,
                "analysis_goal": ""
                if not needs_analysis
                else "Analyze based on data_agent outputs.",
            }
        needs_data = bool(plan.get("needs_data"))
        needs_analysis = bool(plan.get("needs_analysis"))
        print("[Orchestrator] plan_raw:", str(plan_msg.content))
        print("[Orchestrator] plan_parsed:", plan)
        print(f"[Orchestrator] needs_data={needs_data} needs_analysis={needs_analysis}")

        data_query = plan.get("data_query") or user_text
        analysis_goal = plan.get("analysis_goal") or ""

        orchestrator_trace = {
            "needs_data": needs_data,
            "needs_analysis": needs_analysis,
            "data_query": data_query,
            "analysis_goal": analysis_goal,
        }

        if callable(stream_callback):
            try:
                stream_callback(
                    {"type": "orchestrator_plan", "trace": orchestrator_trace}
                )
            except Exception:
                pass

        # 2) DataAgent
        data_response: ToolResponse
        if needs_data:
            if callable(stream_callback):
                try:
                    stream_callback(
                        {
                            "type": "stage",
                            "stage": "data_agent",
                            "message": "Running DataAgent tool steps…",
                        }
                    )
                except Exception:
                    pass
            raw = self.data_agent.invoke(
                {
                    "input": data_query,
                    "context": history_text,
                    "stream_callback": stream_callback,
                }
            )
            data_response = (
                raw.get("output", raw)
                if isinstance(raw, dict)
                else make_tool_response(
                    tool_name="data_agent",
                    message=str(raw),
                    error=False,
                )
            )
        else:
            # No data needed: answer directly with orchestrator
            data_response = make_tool_response(
                tool_name="orchestrator",
                message=user_text,  # placeholder; next step will answer properly
                error=False,
            )

        # If DataAgent paused (e.g. location confirmation), return immediately and
        # attach orchestrator metadata so the UI can resume without replanning.
        if isinstance(data_response, dict):
            data_data = (
                data_response.get("data")
                if isinstance(data_response.get("data"), dict)
                else {}
            )
            if bool(data_data.get("needs_location_confirmation")) is True:
                pause = (
                    data_data.get("pause")
                    if isinstance(data_data.get("pause"), dict)
                    else {}
                )
                data_response["data"] = {
                    **dict(data_data),
                    "orchestrator_trace": orchestrator_trace,
                    "pause": {
                        **dict(pause),
                        "orchestrator_trace": orchestrator_trace,
                        "needs_analysis": needs_analysis,
                        "analysis_goal": analysis_goal,
                        "user_text": user_text,
                    },
                }
                return {"output": data_response}

        # 3) If no data needed and no analysis needed: answer directly (no tools)
        if not needs_data and not needs_analysis:
            # You can keep this as a direct LLM answer (or route to general_question_tool).
            answer_llm = get_chat_llm()
            direct_user_text = augmented_user_text if history_text else user_text
            msg = answer_llm.invoke(
                [
                    SystemMessage(
                        content="Answer the user concisely and directly. Do not invent data."
                    ),
                    HumanMessage(content=direct_user_text),
                ]
            )
            resp = make_tool_response(
                tool_name="orchestrator", message=str(msg.content), error=False
            )
            resp_data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
            resp["data"] = {**dict(resp_data), "orchestrator_trace": orchestrator_trace}
            return {"output": resp}

        # 4) AnalysisAgent (optional)
        if needs_analysis:
            if callable(stream_callback):
                try:
                    stream_callback(
                        {
                            "type": "stage",
                            "stage": "analysis_agent",
                            "message": "Writing analysis based on gathered data…",
                        }
                    )
                except Exception:
                    pass
            analysis_raw = self.analysis_agent.invoke(
                {
                    "user_question": f"{user_text}\n\nAnalysis goal: {analysis_goal}".strip(),
                    "data_response": data_response,
                    "context": history_text,
                    "stream_callback": stream_callback,
                }
            )
            analysis_resp = (
                analysis_raw.get("output", analysis_raw)
                if isinstance(analysis_raw, dict)
                else make_tool_response(
                    tool_name="analysis_agent",
                    message=str(analysis_raw),
                    error=False,
                )
            )

            if isinstance(analysis_resp, dict):
                analysis_data = (
                    analysis_resp.get("data")
                    if isinstance(analysis_resp.get("data"), dict)
                    else {}
                )
                analysis_resp["data"] = {
                    **dict(analysis_data),
                    "orchestrator_trace": orchestrator_trace,
                }
            return {"output": analysis_resp}

        # 5) Otherwise: return DataAgent response
        if isinstance(data_response, dict):
            data_data = (
                data_response.get("data")
                if isinstance(data_response.get("data"), dict)
                else {}
            )
            data_response["data"] = {
                **dict(data_data),
                "orchestrator_trace": orchestrator_trace,
            }
        return {"output": data_response}


def create_orchestrator_executor() -> OrchestratorExecutor:
    planner_llm = get_chat_llm()
    data_agent = create_data_agent_executor()
    analysis_agent = create_analysis_agent_executor()
    return OrchestratorExecutor(
        planner_llm=planner_llm, data_agent=data_agent, analysis_agent=analysis_agent
    )
