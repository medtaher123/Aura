"""AgentCore Browser module when disabled or misconfigured."""

from __future__ import annotations

import pytest


def test_run_browser_research_disabled_returns_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCORE_BROWSER_ENABLED", "false")
    from eo_llm.config import get_config

    get_config.cache_clear()
    from eo_llm.adapters.agentcore_browser import run_browser_research

    rows = run_browser_research(
        contextualized_query="ctx",
        user_query="hello",
    )
    get_config.cache_clear()
    assert len(rows) >= 1
    assert "disabled" in rows[0]["title"].lower() or "disabled" in rows[0]["snippet"].lower()
