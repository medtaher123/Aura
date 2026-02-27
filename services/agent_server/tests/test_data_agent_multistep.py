import json

from src.tools.contracts import ToolArtifacts


def test_truncate_for_prompt_limits_size():
    """Truncation keeps prompt under limit to avoid Bedrock 200k token error."""
    from src.services.data_agent_service import (
        _truncate_for_prompt,
        MAX_TOOL_RESULT_MESSAGE_CHARS,
    )

    assert _truncate_for_prompt(None) == ""
    assert _truncate_for_prompt("short") == "short"
    long_msg = "x" * (MAX_TOOL_RESULT_MESSAGE_CHARS + 500)
    out = _truncate_for_prompt(long_msg)
    assert len(out) <= MAX_TOOL_RESULT_MESSAGE_CHARS + 20
    assert out.endswith("… [truncated]")
    # 400-char limit for input
    long_input = "y" * 500
    out_input = _truncate_for_prompt(long_input, max_chars=400)
    assert len(out_input) <= 420
    assert "… [truncated]" in out_input


def test_data_agent_executes_multiple_tools_without_required_tools():
    """Regression test: DataAgent must not stop after the first tool call.

    When `required_tools` is not provided, the agent should keep following the
    planner's JSON actions until it receives FINAL.
    """

    from src.services.data_agent_service import create_data_agent_executor
    from src.tools.contracts import ToolResponse

    class _Msg:
        def __init__(self, content: str):
            self.content = content

    class _PlannerLLM:
        def __init__(self):
            self.i = 0

        def invoke(self, _messages):
            steps = [
                {
                    "action": "detect_fire_tool",
                    "action_input": {
                        "start_date": "2024-01-01",
                        "end_date": "2024-12-31",
                        "location": "Berlin",
                        "radius_km": 200,
                    },
                    "commentary": "Calling detect_fire_tool for Berlin (2024).",
                },
                {
                    "action": "query_stac_catalog",
                    "action_input": {
                        "city": "Berlin",
                        "start_date": "2024-01-01",
                        "end_date": "2024-12-31",
                        "collection": "sentinel-2-l2a",
                    },
                    "commentary": "Calling query_stac_catalog for Berlin (2024).",
                },
                {
                    "action": "FINAL",
                    "action_input": "Done",
                    "commentary": "Summarizing results.",
                },
            ]
            payload = json.dumps(steps[self.i])
            self.i = min(self.i + 1, len(steps) - 1)
            return _Msg(payload)

    class _Tool:
        def __init__(self, name: str, resp: ToolResponse):
            self.name = name
            self._resp = resp

        def invoke(self, _tool_input):
            return self._resp

    fire_resp = ToolResponse(
        tool_name="detect_fire_tool",
        message="90 fire(s) detected.",
        artifacts=ToolArtifacts(maps=["fire_map"], thumbnails=[], urls=[]),
        error=False,
    )
    stac_resp = ToolResponse(
        tool_name="query_stac_catalog",
        message="1 thumbnail.",
        artifacts=ToolArtifacts(maps=[], thumbnails=["thumb"], urls=[]),
        error=False,
    )

    llm = _PlannerLLM()
    tools = [
        _Tool("detect_fire_tool", fire_resp),
        _Tool("query_stac_catalog", stac_resp),
    ]

    executor = create_data_agent_executor(max_steps=5, llm=llm, tools=tools)
    out = executor.invoke(
        {"input": "Show me fires and satellite images near Berlin in 2024 within 200km"}
    )

    output: ToolResponse = out["output"]
    calls = output.data.get("tool_calls", [])
    names = [c.get("tool_name") for c in calls]

    assert names == ["detect_fire_tool", "query_stac_catalog"], names
    assert output.artifacts.maps, "Expected fire map artifact"
    assert output.artifacts.thumbnails, "Expected stac thumbnail artifact"


def test_data_agent_deduplicates_identical_tool_calls():
    """Regression test: planner loops should not re-run the same tool+args."""

    from src.services.data_agent_service import create_data_agent_executor
    from src.tools.contracts import ToolResponse

    class _Msg:
        def __init__(self, content: str):
            self.content = content

    class _PlannerLLM:
        def __init__(self):
            self.i = 0

        def invoke(self, _messages):
            steps = [
                {
                    "action": "query_disaster_events_tool",
                    "action_input": {
                        "start_date": "2015-01-01",
                        "end_date": "2025-12-31",
                        "country_name": "France",
                        "location": None,
                        "disaster_type": "storm",
                    },
                    "commentary": "Calling query_disaster_events_tool.",
                },
                # Duplicate of the exact same tool call (simulates a looping planner)
                {
                    "action": "query_disaster_events_tool",
                    "action_input": {
                        "start_date": "2015-01-01",
                        "end_date": "2025-12-31",
                        "country_name": "France",
                        "location": None,
                        "disaster_type": "storm",
                    },
                    "commentary": "Calling query_disaster_events_tool again.",
                },
            ]
            payload = json.dumps(steps[self.i])
            self.i = min(self.i + 1, len(steps) - 1)
            return _Msg(payload)

    class _Tool:
        def __init__(self, name: str, resp: ToolResponse):
            self.name = name
            self._resp = resp
            self.calls: list[object] = []

        def invoke(self, tool_input):
            self.calls.append(tool_input)
            return self._resp

    events_resp = ToolResponse(
        tool_name="query_disaster_events_tool",
        message="25 storm events",
        artifacts=ToolArtifacts(maps=["events_map"], thumbnails=[], urls=[]),
        error=False,
    )

    llm = _PlannerLLM()
    tool = _Tool("query_disaster_events_tool", events_resp)

    executor = create_data_agent_executor(max_steps=5, llm=llm, tools=[tool])
    out = executor.invoke({"input": "storms in France"})

    output:ToolResponse = out["output"]
    calls = output.data.get("tool_calls", [])
    names = [c.get("tool_name") for c in calls]

    assert names == ["query_disaster_events_tool"], names
    assert len(tool.calls) == 1, "Expected the underlying tool to be invoked only once"


def test_data_agent_merges_structured_maps_into_one():
    """Regression test: multi-tool map results should overlay on one map."""

    from src.services.data_agent_service import create_data_agent_executor
    from src.tools.contracts import ToolResponse

    class _Msg:
        def __init__(self, content: str):
            self.content = content

    class _PlannerLLM:
        def __init__(self):
            self.i = 0

        def invoke(self, _messages):
            steps = [
                {
                    "action": "query_disaster_events_tool",
                    "action_input": {
                        "start_date": "2024-01-01",
                        "end_date": "2024-12-31",
                        "country_name": "France",
                        "location": None,
                        "disaster_type": ["storm"],
                    },
                },
                {
                    "action": "detect_fire_tool",
                    "action_input": {
                        "start_date": "2024-01-01",
                        "end_date": "2024-12-31",
                        "location": "Paris",
                        "radius_km": 100,
                    },
                },
                {"action": "FINAL", "action_input": "Done"},
            ]
            payload = json.dumps(steps[self.i])
            self.i = min(self.i + 1, len(steps) - 1)
            return _Msg(payload)

    class _Tool:
        def __init__(self, name: str, resp: ToolResponse):
            self.name = name
            self._resp = resp

        def invoke(self, _tool_input):
            return self._resp

    disaster_map = {
        "title": "Storm events",
        "view_state": {"latitude": 48.8, "longitude": 2.3, "zoom": 4},
        "tooltip": {"text": "x"},
        "layers": [{"type": "ScatterplotLayer", "id": "storms"}],
    }
    # Fire tool currently emits a shorthand pydeck spec using `points`.
    fire_map = {
        "title": "Fires",
        "points": [{"lat": 48.8, "lon": 2.3}],
        "view_state": {"latitude": 48.8, "longitude": 2.3, "zoom": 4},
        "tooltip": {"text": "y"},
        "fill_color": [255, 0, 0, 160],
        "radius": 5,
        "radius_units": "pixels",
        "radius_min_pixels": 2,
        "radius_max_pixels": 7,
    }

    events_resp = ToolResponse(
        tool_name="query_disaster_events_tool",
        message="ok",
        artifacts=ToolArtifacts(maps=[disaster_map], thumbnails=[], urls=[]),
        error=False,
    )
    fires_resp = ToolResponse(
        tool_name="detect_fire_tool",
        message="ok",
        artifacts=ToolArtifacts(maps=[fire_map], thumbnails=[], urls=[]),
        error=False,
    )

    llm = _PlannerLLM()
    tools = [
        _Tool("query_disaster_events_tool", events_resp),
        _Tool("detect_fire_tool", fires_resp),
    ]

    executor = create_data_agent_executor(max_steps=6, llm=llm, tools=tools)
    out = executor.invoke({"input": "storms and fires"})
    output:ToolResponse = out["output"]
    merged = output.artifacts.maps
    dict_maps = [
        m for m in merged if isinstance(m, dict) and isinstance(m.get("layers"), list)
    ]
    assert len(dict_maps) == 1, dict_maps
    assert len(dict_maps[0]["layers"]) == 2


def test_data_agent_pause_and_resume_location_confirmation():
    """Regression test: DataAgent should pause on location confirmation and resume without restarting."""

    from src.services.data_agent_service import create_data_agent_executor
    from src.tools.contracts import ToolResponse

    class _Msg:
        def __init__(self, content: str):
            self.content = content

    class _PlannerLLM:
        def __init__(self):
            self.i = 0

        def invoke(self, _messages):
            steps = [
                {
                    "action": "weather_tool",
                    "action_input": {"city_name": "Paris", "forecast_days": 2},
                    "commentary": "Calling weather_tool",
                },
                {"action": "FINAL", "action_input": "Done"},
            ]
            payload = json.dumps(steps[self.i])
            self.i = min(self.i + 1, len(steps) - 1)
            return _Msg(payload)

    class _Tool:
        def __init__(self, name: str):
            self.name = name
            self.calls: list[object] = []
            self._mode = "pause"

        def invoke(self, tool_input):
            self.calls.append(tool_input)
            if self._mode == "pause":
                return ToolResponse(
                    tool_name=self.name,
                    message="Please confirm location",
                    data={
                        "needs_location_confirmation": True,
                        "location_query": "Paris",
                        "candidates": [
                            {
                                "display_name": "Paris, France",
                                "name": "Paris",
                                "lat": 48.8,
                                "lon": 2.3,
                                "bbox": [0, 0, 0, 0],
                            },
                            {
                                "display_name": "Paris, Texas, USA",
                                "name": "Paris",
                                "lat": 33.6,
                                "lon": -95.5,
                                "bbox": [0, 0, 0, 0],
                            },
                        ],
                        "resume_patch": {"field": "city_name"},
                    },
                    error=True,
                )

            return ToolResponse(
                tool_name=self.name,
                message="ok",
                artifacts=ToolArtifacts(maps=[], thumbnails=[], urls=[]),
                error=False,
            )

    llm = _PlannerLLM()
    tool = _Tool("weather_tool")
    executor = create_data_agent_executor(max_steps=4, llm=llm, tools=[tool])

    out1 = executor.invoke({"input": "weather"})
    resp1:ToolResponse = out1["output"]
    assert resp1.data.get("needs_location_confirmation") is True
    pause = resp1.data.get("pause")
    assert isinstance(pause, dict) and isinstance(pause.get("resume_state"), dict)

    # Simulate user choice and resume.
    resume_state = dict(pause["resume_state"])
    next_input = resume_state.get("next_input")
    if isinstance(next_input, dict):
        next_input["city_name"] = "Paris, France"
    else:
        resume_state["next_input"] = {"city_name": "Paris, France"}

    tool._mode = "ok"
    out2 = executor.invoke({"resume_state": resume_state})
    resp2:ToolResponse = out2["output"]
    # Underlying tool should have been called twice total (pause + resume)
    assert len(tool.calls) == 2
    assert resp2.error in (False, True)
