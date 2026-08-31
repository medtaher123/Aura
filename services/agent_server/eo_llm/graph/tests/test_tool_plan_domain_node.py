"""Unit tests for ToolPlanDomainNode base behavior."""

from __future__ import annotations

from typing import Any

import pytest

from eo_llm.graph.nodes.domain_base import (
    DomainTool,
    ModuleTools,
    ProviderTools,
    ToolPlanDomainNode,
)
from eo_llm.graph.tests.conftest import simulate_hitl_resume
from eo_llm.graph.nodes.helpers import LocationContext, omit_none
from eo_llm.graph.tool_plan import (
    ToolExecutionResult,
    ToolExecutionSummary,
    ToolPlan,
    ToolStepExecution,
    ToolStepPlan,
    RetryPolicy,
    OnFailurePolicy,
    StopPolicy,
)
from src.schemas.spatial import BoundingBox
from src.tools.contracts import ToolResponse
from src.tools.providers.base import ProviderHealth, ToolDescriptor, ToolProvider
from src.tools.runtime.registry import ToolRegistry


class _NamedToolsProvider(ToolProvider):
    def __init__(
        self,
        provider_id: str,
        names: list[str],
        *,
        source: str = "mcp",
        modules: dict[str, str] | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._names = names
        self._source = source
        self._modules = modules or {}

    @property
    def provider_id(self) -> str:
        return self._provider_id

    async def discover_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                id=None,
                name=name,
                source=self._source,  # type: ignore[arg-type]
                provider_id=self._provider_id,
                description=name,
                input_schema={},
                module=self._modules.get(name),
            )
            for name in self._names
        ]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResponse:
        return ToolResponse(tool_name=name, message=self._provider_id)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self._provider_id, healthy=True)


class _StubToolPlanDomainNode(ToolPlanDomainNode):
    domain_name = "stub_domain"
    tools = ["stub_tool"]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        return {
            "stub_tool": omit_none(
                {
                    **ctx.known_coords(),
                    "location": ctx.display_name or None,
                }
            )
        }


class _FloodLikeDomainNode(ToolPlanDomainNode):
    domain_name = "flood_like"
    tools = [
        "get_terrazard_flood_briefing_tool",
        DomainTool(
            "get_terrazard_flood_damage_tool",
            required_user_inputs=("bounding_box",),
        ),
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        return {
            "get_terrazard_flood_damage_tool": omit_none(
                {
                    "location": ctx.display_name or None,
                    **ctx.known_coords(),
                    "bbox": ctx.bbox_args,
                }
            )
        }


def _state(**overrides: Any) -> dict[str, Any]:
    base = {
        "query": "fires near Paris",
        "user_query": "fires near Paris",
        "selected_domains": ["stub_domain"],
        "resolved_location": {
            "display_name": "Paris, France",
            "lat": 48.8566,
            "lon": 2.3522,
        },
    }
    base.update(overrides)
    return base


def _damage_plan() -> ToolPlan:
    return ToolPlan(
        domain="flood_damage",
        tool_steps=[
            ToolStepPlan(
                step_id="s1",
                tool_name="get_terrazard_flood_damage_tool",
                priority=1,
                args_template={"observation_date": "2024-03-15"},
                retry_policy=RetryPolicy(),
                on_failure=OnFailurePolicy(),
            )
        ],
        stop_policy=StopPolicy(),
    )


@pytest.mark.asyncio
async def test_tool_plan_domain_not_selected_returns_empty() -> None:
    node = _StubToolPlanDomainNode()
    out = await node(_state(selected_domains=["other"]))
    assert out == {}


@pytest.mark.asyncio
async def test_tool_plan_domain_omits_missing_coordinates() -> None:
    """Without resolved lat/lon, still plan/execute and leave coords for the LLM."""
    captured: dict[str, Any] = {}

    class ReadyNode(_StubToolPlanDomainNode):
        async def select_tool_plan(self, query: str) -> ToolPlan:
            return ToolPlan(
                domain="stub_domain",
                tool_steps=[],
                stop_policy=StopPolicy(),
            )

        async def execute_tool_plan(self, **kwargs):
            captured.update(kwargs)
            return ToolExecutionResult(
                domain="stub_domain",
                steps=[],
                summary=ToolExecutionSummary(successful_steps=0),
            )

    node = ReadyNode()
    out = await node(_state(resolved_location={"display_name": "Paris, France"}))
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "error"  # no successful steps
    runtime = captured["runtime_args_by_tool"]["stub_tool"]
    assert "lat" not in runtime
    assert "lon" not in runtime
    assert runtime.get("location") == "Paris, France"


@pytest.mark.asyncio
async def test_tool_plan_domain_success_envelope() -> None:
    class SuccessNode(_StubToolPlanDomainNode):
        async def select_tool_plan(self, query: str) -> ToolPlan:
            assert query == "fires near Paris"
            return ToolPlan(
                domain="stub_domain",
                tool_steps=[],
                stop_policy=StopPolicy(),
            )

        async def execute_tool_plan(self, **kwargs):
            step = ToolStepExecution(
                step_id="s1",
                tool_name="detect_fire_tool",
                status="done",
                attempts=1,
                latency_ms=1,
                input_arguments={"lat": 48.8566},
                result={"tool_name": "detect_fire_tool", "message": "ok"},
            )
            return ToolExecutionResult(
                domain="stub_domain",
                steps=[step],
                summary=ToolExecutionSummary(successful_steps=1),
            )

    node = SuccessNode()
    out = await node(_state())
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "done"
    assert result["tool"] == "detect_fire_tool"
    assert result["summary"]["successful_steps"] == 1


def test_tool_plan_domain_tools_registry() -> None:
    from eo_llm.graph.builder import build_graph

    build_graph()
    # ModuleTools entries need a live registry; without one only shared tools remain.
    assert ToolPlanDomainNode.tools_for("stac") == ["web_search_tool"]
    assert ToolPlanDomainNode.tools_for("unknown") == []
    # Explicit DomainTool entries still resolve without a registry.
    assert "get_terrazard_flood_damage_tool" in ToolPlanDomainNode.tools_for(
        "flood_damage"
    )


@pytest.mark.asyncio
async def test_stac_domain_resolves_imagery_module(monkeypatch) -> None:
    from eo_llm.graph.builder import build_graph
    from eo_llm.graph.nodes.domains.stac_node import StacNode

    build_graph()
    registry = ToolRegistry()
    await registry.sync_provider_tools(
        _NamedToolsProvider(
            "metaplanet",
            ["query_stac_catalog", "maxar_open_data_imagery_tool", "weather_tool"],
            modules={
                "query_stac_catalog": "imagery",
                "maxar_open_data_imagery_tool": "imagery",
                "weather_tool": "weather",
            },
        )
    )
    monkeypatch.setattr(
        "eo_llm.graph.nodes.domain_base._tool_gateway_registry",
        lambda: registry,
    )
    # shared web_search_tool is dropped when absent from the live registry.
    assert StacNode.resolved_tools() == [
        "maxar_open_data_imagery_tool",
        "query_stac_catalog",
    ]


def test_tool_plan_domain_resolved_tools_merge_shared() -> None:
    assert _StubToolPlanDomainNode.resolved_tools() == [
        "web_search_tool",
        "stub_tool",
    ]
    assert _StubToolPlanDomainNode.shared_tools == ["web_search_tool"]
    assert _FloodLikeDomainNode.resolved_tools() == [
        "web_search_tool",
        "get_terrazard_flood_briefing_tool",
        "get_terrazard_flood_damage_tool",
    ]
    specs = _FloodLikeDomainNode.tool_specs()
    assert specs["get_terrazard_flood_damage_tool"].required_user_inputs == (
        "bounding_box",
    )


@pytest.mark.asyncio
async def test_provider_tools_expand_include_and_exclude() -> None:
    registry = ToolRegistry()
    await registry.sync_provider_tools(
        _NamedToolsProvider("demo", ["alpha", "beta", "gamma"])
    )

    all_tools = ProviderTools("demo").tool_names(registry)
    assert all_tools == ["alpha", "beta", "gamma"]

    subset = ProviderTools("demo", include=("alpha", "gamma")).tool_names(registry)
    assert subset == ["alpha", "gamma"]

    filtered = ProviderTools("demo", exclude=("beta",)).tool_names(registry)
    assert filtered == ["alpha", "gamma"]


@pytest.mark.asyncio
async def test_module_tools_expand_by_module_tag() -> None:
    registry = ToolRegistry()
    await registry.sync_provider_tools(
        _NamedToolsProvider(
            "metaplanet",
            ["detect_fire_tool", "weather_tool", "query_stac_catalog"],
            modules={
                "detect_fire_tool": "hazards",
                "weather_tool": "weather",
                "query_stac_catalog": "imagery",
            },
        )
    )

    hazards = ModuleTools("hazards").tool_names(registry)
    assert hazards == ["detect_fire_tool"]

    imagery = ModuleTools("imagery", include=("query_stac_catalog",)).tool_names(
        registry
    )
    assert imagery == ["query_stac_catalog"]

    empty = ModuleTools("flood").tool_names(registry)
    assert empty == []


@pytest.mark.asyncio
async def test_domain_node_resolves_module_tools(monkeypatch) -> None:
    registry = ToolRegistry()
    await registry.sync_provider_tools(
        _NamedToolsProvider(
            "metaplanet",
            ["detect_fire_tool", "clms_burnt_area_impact_tool", "weather_tool"],
            modules={
                "detect_fire_tool": "hazards",
                "clms_burnt_area_impact_tool": "hazards",
                "weather_tool": "weather",
            },
        )
    )
    monkeypatch.setattr(
        "eo_llm.graph.nodes.domain_base._tool_gateway_registry",
        lambda: registry,
    )

    class HazardsDomainNode(ToolPlanDomainNode):
        domain_name = "hazards_domain"
        tools = [
            ModuleTools("hazards"),
            DomainTool("extra_explicit"),
        ]

        def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
            return {}

    assert HazardsDomainNode.resolved_tools() == [
        "clms_burnt_area_impact_tool",
        "detect_fire_tool",
    ]
    assert HazardsDomainNode.tool_specs() == {
        "extra_explicit": DomainTool("extra_explicit"),
    }


@pytest.mark.asyncio
async def test_domain_node_resolves_provider_tools(monkeypatch) -> None:
    registry = ToolRegistry()
    await registry.sync_provider_tools(
        _NamedToolsProvider(
            "native",
            ["calculator", "request_location_user_input"],
            source="native",
        )
    )
    monkeypatch.setattr(
        "eo_llm.graph.nodes.domain_base._tool_gateway_registry",
        lambda: registry,
    )

    class ProviderDomainNode(ToolPlanDomainNode):
        domain_name = "provider_domain"
        tools = [
            ProviderTools("native"),
            DomainTool("extra_explicit"),
        ]

        def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
            return {}

    # Availability filter drops tools not in the registry.
    assert ProviderDomainNode.resolved_tools() == [
        "calculator",
        "request_location_user_input",
    ]
    assert ProviderDomainNode.tools_for("provider_domain") == [
        "calculator",
        "request_location_user_input",
    ]
    assert ProviderDomainNode.tool_specs() == {
        "extra_explicit": DomainTool("extra_explicit"),
    }


@pytest.mark.asyncio
async def test_tool_plan_domain_error_envelope() -> None:
    class FailingNode(_StubToolPlanDomainNode):
        async def select_tool_plan(self, query: str) -> ToolPlan:
            raise RuntimeError("planner unavailable")

        async def execute_tool_plan(self, **kwargs):
            raise AssertionError("should not execute")

    node = FailingNode()
    out = await node(_state())
    result = out["domain_results"]["stub_domain"]
    assert result["status"] == "error"
    assert "planner unavailable" in result["message"]
    assert result["summary"]["successful_steps"] == 0


@pytest.mark.asyncio
async def test_tool_plan_domain_pauses_for_missing_bbox(monkeypatch) -> None:
    class PauseNode(_FloodLikeDomainNode):
        async def select_tool_plan(self, query: str) -> ToolPlan:
            return _damage_plan()

        async def execute_tool_plan(self, **kwargs):
            step = ToolStepExecution(
                step_id="s1",
                tool_name="get_terrazard_flood_damage_tool",
                status="done",
                attempts=1,
                latency_ms=1,
                input_arguments={"bbox": [48.0, 49.0, 2.0, 3.0]},
                result={
                    "tool_name": "get_terrazard_flood_damage_tool",
                    "message": "ok",
                },
            )
            return ToolExecutionResult(
                domain="flood_like",
                steps=[step],
                summary=ToolExecutionSummary(successful_steps=1),
            )

    async def fake_pause(self, s, client_payload, *, blob=None):
        return await simulate_hitl_resume(
            self,
            s,
            [
                {
                    "type": "bounding_box",
                    "area": {
                        "kind": "bounding_box",
                        "min_lat": 48.0,
                        "max_lat": 49.0,
                        "min_lon": 2.0,
                        "max_lon": 3.0,
                    },
                }
            ],
            blob=blob,
        )

    monkeypatch.setattr(PauseNode, "pause_for_hitl", fake_pause)

    node = PauseNode()
    out = await node(
        _state(
            query="flood damage in Paris",
            selected_domains=["flood_like"],
        )
    )
    result = out["domain_results"]["flood_like"]
    assert result["status"] == "done"


@pytest.mark.asyncio
async def test_tool_plan_domain_executes_when_bbox_present() -> None:
    executed: dict[str, Any] = {}

    class ReadyNode(_FloodLikeDomainNode):
        async def select_tool_plan(self, query: str) -> ToolPlan:
            return _damage_plan()

        async def execute_tool_plan(self, **kwargs):
            executed.update(kwargs)
            step = ToolStepExecution(
                step_id="s1",
                tool_name="get_terrazard_flood_damage_tool",
                status="done",
                attempts=1,
                latency_ms=1,
                input_arguments={"bbox": [48.0, 49.0, 2.0, 3.0]},
                result={
                    "tool_name": "get_terrazard_flood_damage_tool",
                    "message": "ok",
                },
            )
            return ToolExecutionResult(
                domain="flood_like",
                steps=[step],
                summary=ToolExecutionSummary(successful_steps=1),
            )

    node = ReadyNode()
    out = await node(
        _state(
            query="flood damage in Paris",
            selected_domains=["flood_like"],
            resolved_area={
                "kind": "bounding_box",
                "min_lat": 48.0,
                "max_lat": 49.0,
                "min_lon": 2.0,
                "max_lon": 3.0,
            },
        )
    )
    result = out["domain_results"]["flood_like"]
    assert result["status"] == "done"
    runtime = executed["runtime_args_by_tool"]["get_terrazard_flood_damage_tool"]
    assert runtime["bbox"] == {
        "min_lat": 48.0,
        "max_lat": 49.0,
        "min_lon": 2.0,
        "max_lon": 3.0,
    }



def test_location_context_exposes_bbox() -> None:
    from eo_llm.graph.state import validate_state

    s = validate_state(
        _state(
            resolved_area={
                "kind": "bounding_box",
                "min_lat": 1.0,
                "max_lat": 2.0,
                "min_lon": 3.0,
                "max_lon": 4.0,
            }
        )
    )
    ctx = LocationContext.from_state(s)
    assert isinstance(ctx.resolved_area, BoundingBox)
    assert ctx.bbox_list == [1.0, 2.0, 3.0, 4.0]
    assert ctx.bbox_args == {
        "min_lat": 1.0,
        "max_lat": 2.0,
        "min_lon": 3.0,
        "max_lon": 4.0,
    }
