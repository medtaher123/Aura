#agent_service.py
from langchain.tools import tool
from langchain_ollama import OllamaLLM
from langchain.agents import initialize_agent, AgentType
from ..tools.tools_risk import get_all_tools
from ..core.prompts import get_prompt_config
from ..services.translate_service import translate_from_english


# ---------------------------------------------------
# CREATE AGENT EXECUTOR
# ---------------------------------------------------

def create_agent_executor():
    """
    Initialize the structured chat agent (stateless)
    """
    # Prompt
    prompt_template = get_prompt_config("few_shot")

    # LLM
    llm = OllamaLLM(
        model="mistral",
        temperature=0.1,
        system_prompt=prompt_template,
    )

    # Tools
    tools = get_all_tools()

    agent_executor = initialize_agent(
        llm=llm,
        tools=tools,
        agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=False,
        max_iterations=5
    )

    return agent_executor

