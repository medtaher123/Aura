"""Session context passed to Bedrock-backed graph operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMSessionContext:
    task_id: str
    session_id: str
    user_id: str
