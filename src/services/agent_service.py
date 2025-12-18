# src/services/agent_service.py
from __future__ import annotations

from .langgraph_agent_service import create_langgraph_agent_executor

# ---------------------------------------------------
# CREATE AGENT EXECUTOR (LANGGRAPH ONLY)
# ---------------------------------------------------
def create_agent_executor():
    """
    Initialize the agent executor (LangGraph-only).
    """
    return create_langgraph_agent_executor()