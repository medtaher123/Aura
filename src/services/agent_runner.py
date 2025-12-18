from __future__ import annotations

from typing import Any, Dict


def invoke_agent(executor: Any, english_query: str) -> Any:
    """
    Single place that defines the agent contract used by the UI:
    - Call: executor.invoke({"input": english_query})
    - Prefer returning response["output"] when available
    - Otherwise return the raw response (for future flexibility)
    """
    response = executor.invoke({"input": english_query})

    if isinstance(response, dict):
        print(f"Debug: Agent response dictionary: {response}")
        return response.get("output", response)
    print(f"Debug: Agent response: {response}")
    return response