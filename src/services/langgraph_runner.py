"""
Minimal LangGraph scaffold to validate that LangGraph works with the current
Ollama-backed LLM setup. This does not change existing agent code.
"""
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, MessagesState, StateGraph


class BasicGraphConfig(TypedDict, total=False):
    """Runtime options for the basic graph."""

    model: str
    temperature: float
    system_prompt: str


def build_basic_graph(config: BasicGraphConfig | None = None):
    """
    Build a single-node LangGraph that echoes a reply from the configured LLM.

    Returns a compiled graph so it can be invoked or streamed.
    """

    cfg: dict[str, Any] = {
        "model": "mistral",
        "temperature": 0.1,
        "system_prompt": None,
    }
    if config:
        cfg.update({k: v for k, v in config.items() if v is not None})

    llm = ChatOllama(model=cfg["model"], temperature=cfg["temperature"])
    if cfg.get("system_prompt"):
        llm = llm.bind(system=cfg["system_prompt"])

    graph = StateGraph(MessagesState)

    def llm_node(state: MessagesState):
        response = llm.invoke(state["messages"])
        return {"messages": state["messages"] + [response]}

    graph.add_node("llm", llm_node)
    graph.set_entry_point("llm")
    graph.add_edge("llm", END)

    return graph.compile(checkpointer=MemorySaver())


def run_basic_graph(user_input: str, config: BasicGraphConfig | None = None) -> str:
    """Convenience helper to run the basic graph once and return the text reply."""

    app = build_basic_graph(config)
    result = app.invoke({"messages": [HumanMessage(user_input)]})
    return result["messages"][-1].content
