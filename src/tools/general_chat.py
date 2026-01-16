from langchain.tools import tool
from src.services.llm_service import get_chat_llm

from .contracts import make_tool_response


# Overridable for tests; defaults to lazy Bedrock initialization.
llm = None

@tool(return_direct=True)
def general_question_tool(query_text: str) -> dict:
    """
    Tool for answering general questions, explanations, summaries,
    or conversational queries that are not related to the other tools.
    The answer must be concise and directly address the question.
    """
    try:
        active_llm = llm if llm is not None else get_chat_llm()
        prompt = f"""
        You are a precise assistant for earth observation tasks.

        Rules:
        - Answer ONLY the user's question
        - Be concise and brief
        - Do NOT introduce new topics
        - Do NOT add explanations unless asked
        - Do NOT hallucinate information
        - If the question is unclear, ask for clarification

        User question:
        {query_text}

        Answer:
        """

        response = active_llm.invoke(prompt)
        content = getattr(response, "content", None)
        if content is None:
            content = str(response)
        return make_tool_response(
            tool_name="general_question_tool",
            message=str(content),
            error=False,
        )
    except Exception as e:
        return make_tool_response(
            tool_name="general_question_tool",
            message=f"Error while answering general question: {str(e)}",
            error=True,
        )
