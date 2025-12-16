#agent_service.py
from langchain.tools import tool
from langchain_ollama import OllamaLLM
from langchain.agents import initialize_agent, AgentType
from ..tools.tools_risk import get_all_tools, extract_bbox_and_dates, query_stac_catalog_with_retry
from ..core.prompts import get_prompt_config
from ..services.translate_service import translate_from_english
from langchain.memory import ConversationBufferWindowMemory


# ---------------------------------------------------
# TOOL: Build query parameters from user input
# ---------------------------------------------------
@tool
def build_query_params_from_input(user_input: str) -> str:
    """
    Extracts bbox, dates, collection from a free-text input and builds
    the 'params' string expected by STAC.
    """
    extraction_result = extract_bbox_and_dates(user_input)

    if "error" in extraction_result:
        return extraction_result["error"]

    bbox = extraction_result["bbox"]
    start_date = extraction_result["start_date"]
    end_date = extraction_result["end_date"]
    collection = extraction_result["collection"]

    return f"{bbox} {start_date} {end_date} {collection}"


# ---------------------------------------------------
# CREATE AGENT EXECUTOR
# ---------------------------------------------------

def create_agent_executor():
    """
    Initialize the structured chat agent with memory
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

    # Memory
    memory = ConversationBufferWindowMemory(
        memory_key="chat_history",
        k=7,  # keep only last 5 messages
        return_messages=True
    )
    # Agent with memory
    agent_executor = initialize_agent(
        llm=llm,
        tools=tools,
        agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        max_iterations=5
    )

    return agent_executor



# ---------------------------------------------------
# RUN DIRECT STAC QUERY
# ---------------------------------------------------
def run_query_direct(user_input: str, user_lang: str = "en"):
    """
    Runs a direct STAC query using extracted bbox, dates, collection.
    Also translates the 'message' field back to the user's language if needed.
    """
    print("Running direct STAC query...")
    result = extract_bbox_and_dates(user_input)
    print(f"Extracted parameters: {result}")
    if "error" in result:
        return {"message": result["error"], "error": True}

    bbox = result["bbox"]
    start = result["start_date"]
    end = result["end_date"]
    collection = result["collection"]

    params = f"{bbox} {start} {end} {collection}"

    query_result = query_stac_catalog_with_retry(params)

    # Ensure 'message' is translated back to user's language
    if isinstance(query_result, dict) and "message" in query_result:
        query_result["message"] = translate_from_english(query_result["message"], user_lang)

    return query_result