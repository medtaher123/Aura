"""Orchestrator Agent Service.

Main coordinator that routes user requests to DataAgent and/or AnalysisAgent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, cast

from langchain_core.messages import HumanMessage, SystemMessage
from .llm_service import get_chat_llm

from ..core.logger import get_logger
from ..core.prompts import get_orchestrator_prompt
from ..core.memory import format_chat_history
from ..tools.contracts import ToolResponse
from ..api.models import OrchestratorInputs, OrchestratorTrace, ResumeState
from .data_agent_service import create_data_agent_executor
from .analysis_agent_service import create_analysis_agent_executor

logger = get_logger("orchestrator")


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
    """Main orchestrator that coordinates DataAgent and AnalysisAgent."""

    planner_llm: Any
    data_agent: Any
    analysis_agent: Any

    def invoke(self, inputs: OrchestratorInputs) -> Dict[str, Any]:
        """Invoke the orchestrator.

        Args:
            inputs: Dict containing:
                - input: User message
                - chat_history: Previous conversation (optional)
                - stream_callback: Callback for streaming updates (optional)
                - resume: Resume state for paused agents (optional)

        Returns:
            Dict with 'output' containing the final ToolResponse
        """
        user_text = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        chat_history = inputs.get("chat_history") if isinstance(inputs, dict) else None
        stream_callback = (
            inputs.get("stream_callback") if isinstance(inputs, dict) else None
        )
        history_text = format_chat_history(
            chat_history, max_messages=12, max_chars=6000
        )

        # Resume path: continue from a paused DataAgent state without replanning.
        resume: Optional[ResumeState] = (
            inputs.get("resume") if isinstance(inputs, dict) else None
        )
        if isinstance(resume, dict) and isinstance(resume.get("resume_state"), dict):
            logger.info("Orchestrator resuming from pause state")
            resume_state: Dict[str, Any] = cast(
                Dict[str, Any], resume.get("resume_state")
            )
            # debug resume_state
            logger.debug(f"Resume state: {json.dumps(resume_state, indent=2)}")
            orchestrator_trace: OrchestratorTrace = cast(
                OrchestratorTrace,
                resume.get("orchestrator_trace")
                if isinstance(resume.get("orchestrator_trace"), dict)
                else {},
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

            logger.debug(
                f"Resume state - needs_analysis: {needs_analysis}, has_orchestrator_trace: {bool(orchestrator_trace)}, original_user_text: {original_user_text[:100] if original_user_text else 'N/A'}"
            )

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
                    logger.error("Error calling stream_callback", exc_info=True)
                    pass

            raw = self.data_agent.invoke(
                {"resume_state": resume_state, "stream_callback": stream_callback}
            )
            data_response: ToolResponse = raw.get("output")

            # If we paused again (multiple ambiguous locations), return immediately.
            if data_response.data:
                if data_response.data.get("needs_location_confirmation", False):
                    # check if we have confirmed locations in the resume state
                    confirmed_locations = resume_state.get("confirmed_locations")
                    if confirmed_locations:
                        logger.debug(
                            f"Confirmed locations in resume state: {confirmed_locations}"
                        )
                    else:
                        logger.debug("No confirmed locations in resume state")
                    logger.info(
                        "DataAgent paused again during resume - another location confirmation needed"
                    )
                    pause_raw = data_response.data.get("pause", {})
                    logger.debug(f"Pause payload keys: {list(pause_raw.keys())}")
                    data_response.data["orchestrator_trace"] = orchestrator_trace

                    pause_raw["orchestrator_trace"] = orchestrator_trace
                    pause_raw["needs_analysis"] = needs_analysis
                    pause_raw["analysis_goal"] = analysis_goal
                    pause_raw["user_text"] = original_user_text

                    data_response.data["pause"] = pause_raw

                    logger.debug(
                        f"Enriched pause state with orchestrator context - has_resume_state: {'resume_state' in pause_raw}"
                    )
                    return {"output": data_response}

            # AnalysisAgent (optional) after data completes.
            if needs_analysis:
                logger.info(
                    f"Invoking AnalysisAgent after resume - analysis_goal: {analysis_goal[:100] if analysis_goal else 'N/A'}"
                )
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
                    else ToolResponse(
                        tool_name="analysis_agent",
                        message=str(analysis_raw),
                        error=False,
                    )
                )

                if isinstance(analysis_resp, dict):
                    analysis_data_raw = analysis_resp.get("data")
                    analysis_data: Dict[str, Any] = (
                        analysis_data_raw if isinstance(analysis_data_raw, dict) else {}
                    )
                    analysis_resp["data"] = {
                        **analysis_data,
                        "orchestrator_trace": orchestrator_trace,
                    }
                return {"output": analysis_resp}

            data_response.data["orchestrator_trace"] = orchestrator_trace

            return {"output": data_response}

        logger.info(
            f"Orchestrator planning new request - user_text length: {len(user_text)}, has_history: {bool(history_text)}"
        )

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
            logger.warning(
                "Initial planning failed to return valid JSON, retrying with stricter instructions"
            )
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
            logger.warning(
                "Planning retry also failed, falling back to keyword-based heuristics"
            )
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
        logger.debug(f"Orchestrator planning raw output: {str(plan_msg.content)}")
        logger.info(
            f"Orchestrator plan parsed: needs_data={needs_data}, needs_analysis={needs_analysis}, analysis_goal={plan.get('analysis_goal', 'N/A')}"
        )
        logger.debug(f"Orchestrator full plan details: {plan}")

        data_query = plan.get("data_query") or user_text
        analysis_goal = plan.get("analysis_goal") or ""

        orchestrator_trace_new: OrchestratorTrace = {
            "needs_data": needs_data,
            "needs_analysis": needs_analysis,
            "data_query": data_query,
            "analysis_goal": analysis_goal,
        }

        if callable(stream_callback):
            try:
                stream_callback(
                    {"type": "orchestrator_plan", "trace": orchestrator_trace_new}
                )
            except Exception:
                pass

        # 2) DataAgent
        if needs_data:
            logger.info(f"Invoking DataAgent - data_query: {data_query[:100]}")
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
            logger.debug(f"OrchestratorAgentService invoke: raw type={type(raw)}")
            data_response = raw.get("output")

            logger.debug(f"DataAgent completed - response type: {type(data_response)}")
        else:
            logger.info(
                "DataAgent skipped - no data gathering needed per orchestrator plan"
            )
            # No data needed: answer directly with orchestrator
            data_response = ToolResponse(
                tool_name="orchestrator",
                message=user_text,  # placeholder; next step will answer properly
                error=False,
            )

        # If DataAgent paused (e.g. location confirmation), return immediately and
        # attach orchestrator metadata so the UI can resume without replanning.
        if data_response.data:
            if data_response.data.get("needs_location_confirmation", False):
                logger.info("DataAgent paused - location confirmation needed")
                pause_raw = data_response.data.get("pause")
                pause: Dict[str, Any] = pause_raw if isinstance(pause_raw, dict) else {}
                logger.debug(
                    f"Initial pause payload keys: {list(pause.keys())}, has_resume_state: {'resume_state' in pause}"
                )
                data_response.data["orchestrator_trace"] = orchestrator_trace_new
                pause["orchestrator_trace"] = orchestrator_trace_new
                pause["needs_analysis"] = needs_analysis
                pause["analysis_goal"] = analysis_goal
                pause["user_text"] = user_text
                data_response.data["pause"] = pause
                logger.info(
                    f"Enriched pause state with orchestrator context - user_text: {user_text[:100]}, needs_analysis: {needs_analysis}"
                )
                return {"output": data_response}

        # 3) If no data needed and no analysis needed: answer directly (no tools)
        if not needs_data and not needs_analysis:
            logger.info("Answering directly without data or analysis agents")
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
            resp = ToolResponse(
                tool_name="orchestrator", message=str(msg.content), error=False
            )
            resp.data = {**resp.data, "orchestrator_trace": orchestrator_trace_new}
            return {"output": resp}

        # 4) AnalysisAgent (optional)
        if needs_analysis:
            logger.info(
                f"Invoking AnalysisAgent - analysis_goal: {analysis_goal[:100] if analysis_goal else 'N/A'}"
            )
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
                else ToolResponse(
                    tool_name="analysis_agent",
                    message=str(analysis_raw),
                    error=False,
                )
            )

            if isinstance(analysis_resp, dict):
                analysis_data_raw = analysis_resp.get("data")
                analysis_data_final: Dict[str, Any] = (
                    analysis_data_raw if isinstance(analysis_data_raw, dict) else {}
                )
                analysis_resp["data"] = {
                    **analysis_data_final,
                    "orchestrator_trace": orchestrator_trace_new,
                }
            logger.info("Orchestrator workflow completed with AnalysisAgent")
            return {"output": analysis_resp}

        # 5) Otherwise: return DataAgent response
        logger.info("Orchestrator workflow completed with DataAgent only")
        data_response.data["orchestrator_trace"] = orchestrator_trace_new

        return {"output": data_response}


def create_orchestrator_executor() -> OrchestratorExecutor:
    """Create an OrchestratorExecutor instance with all sub-agents."""
    planner_llm = get_chat_llm()
    data_agent = create_data_agent_executor()
    analysis_agent = create_analysis_agent_executor()
    return OrchestratorExecutor(
        planner_llm=planner_llm, data_agent=data_agent, analysis_agent=analysis_agent
    )
