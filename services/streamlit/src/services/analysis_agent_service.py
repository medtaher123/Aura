from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from src.services.llm_service import get_chat_llm

from src.core.prompts import get_analysis_prompt
from src.tools.contracts import ToolResponse, make_tool_response

# Cap size of data_response in analysis prompt to avoid Bedrock "prompt too long" (200k limit)
MAX_DATA_RESPONSE_CHARS = 12000


def _format_data_response_for_prompt(data_response: Any) -> str:
    """Stringify data_response for the analysis prompt, truncating if huge."""
    if data_response is None:
        return "(no data)"
    s = str(data_response)
    if len(s) <= MAX_DATA_RESPONSE_CHARS:
        return s
    return s[: MAX_DATA_RESPONSE_CHARS - 50].rstrip() + "\n… [truncated for length]"


@dataclass
class AnalysisAgentExecutor:
    llm: Any

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_question = inputs.get("user_question", "")
        data_response = inputs.get("data_response", {})
        context = inputs.get("context", "")

        prompt = get_analysis_prompt()

        context_block = ""
        if isinstance(context, str) and context.strip():
            context_block = f"conversation_context:\n{context.strip()}\n\n"

        data_response_text = _format_data_response_for_prompt(data_response)

        msg = self.llm.invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(
                    content=(
                        f"{context_block}"
                        f"user_question:\n{user_question}\n\n"
                        f"data_response:\n{data_response_text}"
                    )
                ),
            ]
        )

        # Preserve artifacts from DataAgent (maps/thumbnails)
        artifacts = (data_response or {}).get("artifacts") if isinstance(data_response, dict) else None

        return {
            "output": make_tool_response(
                tool_name="analysis_agent",
                message=str(msg.content),
                artifacts=artifacts,
                start_date=(data_response or {}).get("start_date") if isinstance(data_response, dict) else None,
                end_date=(data_response or {}).get("end_date") if isinstance(data_response, dict) else None,
                country=(data_response or {}).get("country") if isinstance(data_response, dict) else None,
                city=(data_response or {}).get("city") if isinstance(data_response, dict) else None,
                coordinates=(data_response or {}).get("coordinates") if isinstance(data_response, dict) else None,
                data={"source_tool": (data_response or {}).get("tool_name")} if isinstance(data_response, dict) else None,
                error=False,
            )
        }


def create_analysis_agent_executor() -> AnalysisAgentExecutor:
    llm = get_chat_llm()
    return AnalysisAgentExecutor(llm=llm)