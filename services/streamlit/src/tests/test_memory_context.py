import json


def test_memory_context_is_passed_between_turns():
    """Regression test: follow-up turns must receive prior context.

    This test does NOT validate LLM reasoning quality.
    It validates that the app's "memory" plumbing passes prior turns via:
    - Orchestrator -> planner prompt (augmented_user_text)
    - Orchestrator -> DataAgent `context`
    """

    from src.services.orchestrator_agent_service import OrchestratorExecutor
    from src.tools.contracts import make_tool_response

    class _Msg:
        def __init__(self, content: str):
            self.content = content

    class _PlannerLLM:
        def __init__(self):
            self.human_prompts: list[str] = []

        def invoke(self, messages):
            # messages = [SystemMessage(...), HumanMessage(...)]
            human = messages[-1]
            self.human_prompts.append(str(getattr(human, "content", "")))

            # Always route to data to exercise context propagation.
            plan = {
                "needs_data": True,
                "needs_analysis": False,
                "data_query": "__USE_USER_TEXT__",
                "analysis_goal": "",
            }
            return _Msg(json.dumps(plan))

    class _DataAgent:
        def __init__(self):
            self.calls: list[dict] = []

        def invoke(self, inputs):
            self.calls.append(dict(inputs))
            return {
                "output": make_tool_response(
                    tool_name="data_agent",
                    message="ok",
                    error=False,
                )
            }

    class _AnalysisAgent:
        def invoke(self, inputs):
            return {
                "output": make_tool_response(
                    tool_name="analysis_agent",
                    message="ok",
                    error=False,
                )
            }

    planner = _PlannerLLM()
    data_agent = _DataAgent()
    analysis_agent = _AnalysisAgent()

    executor = OrchestratorExecutor(planner_llm=planner, data_agent=data_agent, analysis_agent=analysis_agent)

    history: list[dict] = []

    q1 = "are there fires in France in 2024?"
    q2 = "are there storms there?"
    q3 = "are there storms in the US?"

    # Turn 1
    executor.invoke({"input": q1, "chat_history": history})
    history.append({"role": "user", "content": q1})
    history.append({"role": "assistant", "content": "(assistant answered about fires in France in 2024)"})

    # Turn 2 (expects to inherit location+date from history)
    executor.invoke({"input": q2, "chat_history": history})
    history.append({"role": "user", "content": q2})
    history.append({"role": "assistant", "content": "(assistant answered about storms in France in 2024)"})

    # Turn 3 (expects to inherit date from history)
    executor.invoke({"input": q3, "chat_history": history})

    # --- Assertions ---
    assert len(planner.human_prompts) == 3

    # Turn 1: no prior context injected
    assert "Conversation so far" not in planner.human_prompts[0]

    # Turn 2: prior context injected into planner prompt
    assert "Conversation so far" in planner.human_prompts[1]
    assert "France" in planner.human_prompts[1]
    assert "2024" in planner.human_prompts[1]
    assert "User request:" in planner.human_prompts[1]
    assert q2 in planner.human_prompts[1]

    # Turn 3: still contains the previously mentioned date
    assert "2024" in planner.human_prompts[2]
    assert q3 in planner.human_prompts[2]

    # DataAgent should have been called for each turn
    assert len(data_agent.calls) == 3

    # For turn 1, context is empty
    assert not (data_agent.calls[0].get("context") or "").strip()

    # For turn 2, context should include France + 2024 from turn 1
    ctx2 = data_agent.calls[1].get("context") or ""
    assert "France" in ctx2
    assert "2024" in ctx2

    # For turn 3, context should still include 2024 (date persistence)
    ctx3 = data_agent.calls[2].get("context") or ""
    assert "2024" in ctx3
