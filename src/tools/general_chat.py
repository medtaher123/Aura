from langchain.tools import tool
from langchain_ollama import OllamaLLM

from .contracts import make_tool_response

# Local LLM via Ollama
llm = OllamaLLM(
    model="mistral",
    temperature=0.1,
)

@tool(return_direct=True)
def general_question_tool(query_text: str) -> dict:
    """
    Tool for answering general questions, explanations, summaries,
    or conversational queries that are not related to the other tools.
    The answer must be concise and directly address the question.
    """
    try:
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

        response = llm.invoke(prompt)
        return make_tool_response(
            tool_name="general_question_tool",
            message=str(response),
            error=False,
        )
    except Exception as e:
        return make_tool_response(
            tool_name="general_question_tool",
            message=f"Error while answering general question: {str(e)}",
            error=True,
        )
