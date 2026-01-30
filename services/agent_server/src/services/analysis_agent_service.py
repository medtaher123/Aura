"""Analysis Agent Service.

Provides analysis and summarization based on DataAgent outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from .llm_service import get_chat_llm
from ..core.logger import get_logger
from ..core.prompts import get_analysis_prompt
from ..tools.contracts import ToolResponse, make_tool_response

logger = get_logger("analysis_agent")


@dataclass
class AnalysisAgentExecutor:
    """Executor for the Analysis Agent."""
    llm: Any

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke the analysis agent.
        
        Args:
            inputs: Dict containing:
                - user_question: The user's original question
                - data_response: ToolResponse from DataAgent
                - context: Conversation context (optional)
                
        Returns:
            Dict with 'output' containing the analysis ToolResponse
        """
        user_question = inputs.get("user_question", "")
        data_response = inputs.get("data_response", {})
        context = inputs.get("context", "")
        
        logger.info(f"AnalysisAgent invoked - question length: {len(user_question)}, has_data_response: {bool(data_response)}, has_context: {bool(context)}")

        prompt = get_analysis_prompt()

        context_block = ""
        if isinstance(context, str) and context.strip():
            context_block = f"conversation_context:\n{context.strip()}\n\n"

        msg = self.llm.invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(
                    content=(
                        f"{context_block}"
                        f"user_question:\n{user_question}\n\n"
                        f"data_response:\n{data_response}"
                    )
                ),
            ]
        )

        # Preserve artifacts from DataAgent (maps/thumbnails)
        artifacts = (data_response or {}).get("artifacts") if isinstance(data_response, dict) else None
        
        logger.info(f"AnalysisAgent completed - response length: {len(str(msg.content))}, preserved_artifacts: {bool(artifacts)}")

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
    """Create an AnalysisAgentExecutor instance."""
    llm = get_chat_llm()
    return AnalysisAgentExecutor(llm=llm)
