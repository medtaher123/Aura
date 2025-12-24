from __future__ import annotations

from .orchestrator_agent_service import create_orchestrator_executor

def create_agent_executor():
    return create_orchestrator_executor()