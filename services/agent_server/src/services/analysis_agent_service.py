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
from ..tools.contracts import ToolResponse

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
        data_response: ToolResponse = inputs.get("data_response", {})
        context = inputs.get("context", "")

        logger.info(
            f"AnalysisAgent invoked - question length: {len(user_question)}, has_data_response: {bool(data_response)}, has_context: {bool(context)}"
        )

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
        artifacts = data_response.artifacts

        logger.info(
            f"AnalysisAgent completed - response length: {len(str(msg.content))}, preserved_artifacts: {bool(artifacts)}"
        )

        return {
            "output": ToolResponse(
                tool_name="analysis_agent",
                message=str(msg.content),
                artifacts=artifacts,
                start_date=data_response.start_date,
                end_date=data_response.end_date,
                country=data_response.country,
                city=data_response.city,
                coordinates=data_response.coordinates,
                data={"source_tool": data_response.tool_name},
                error=data_response.error,
            )
        }


def create_analysis_agent_executor() -> AnalysisAgentExecutor:
    """Create an AnalysisAgentExecutor instance."""
    llm = get_chat_llm()
    return AnalysisAgentExecutor(llm=llm)
