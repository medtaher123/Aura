#llm_service.py
# LLM service module - handles LLM initialization and interactions

from langchain_ollama import OllamaLLM

def get_llm(model: str = "mistral", temperature: float = 0.1):
    """
    Get an initialized LLM instance
    
    Args:
        model: The model name (default: mistral)
        temperature: Temperature setting (default: 0.1)
    
    Returns:
        OllamaLLM instance
    """
    return OllamaLLM(
        model=model,
        temperature=temperature,
    )
