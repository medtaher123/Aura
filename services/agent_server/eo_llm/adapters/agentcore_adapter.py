"""AgentCore integration seam.

Keep this adapter thin so graph code stays framework-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
import json
import logging
import pkgutil
import random
import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.document_store import load_document_bytes
from eo_llm.adapters.mcp_tools_registry import DOMAIN_TOOLS

logger = logging.getLogger("eo_llm.agentcore")

DomainName = Literal[
    "flood_damage",
    "fire_detection",
    "disaster_detection",
    "infrastructure",
    "stac",
    "document_qa",
]
RouteDomain = Literal[
    "flood_damage",
    "fire_detection",
    "disaster_detection",
    "infrastructure",
    "stac",
    "document_qa",
    "tools_info",
    "websearch_only",
]
ToolName = Literal[
    "geoserver_risk_mask_tool",
    "flood_damage_city_tool",
    "flood_depth_damage_tool",
    "streamflow_forecast_tool",
    "estimate_surface_water_ingress_tool",
    "detect_fire_tool",
    "query_disaster_events_tool",
    "infrastructure_query_tool",
    "get_route_info",
    "query_stac_catalog",
    "maxar_open_data_imagery_tool",
]
ExecutionMode = Literal["parallel", "sequential"]
BackoffMode = Literal["none", "fixed", "exponential_jitter"]
FailureAction = Literal["continue", "fallback_to_step", "abort_domain"]
StopMode = Literal["run_all", "stop_on_first_success", "stop_on_confidence"]
ErrorType = Literal[
    "timeout",
    "network_error",
    "http_429",
    "http_5xx",
    "validation_error",
    "empty_result",
    "unknown",
]
RetryTrigger = Literal["timeout", "network_error", "http_429", "http_5xx", "empty_result"]
RouteDecider = Callable[[str], Any]

BEDROCK_ROUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "domains": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "flood_damage",
                    "fire_detection",
                    "disaster_detection",
                    "infrastructure",
                    "stac",
                    "document_qa",
                    "tools_info",
                    "websearch_only",
                ],
            },
        },
        "confidence": {"type": "number"},
        "execution_mode": {"type": "string", "enum": ["parallel", "sequential"]},
        "reasoning": {"type": "string"},
        "needs_web_fallback_if_low_confidence": {"type": "boolean"},
        "stop_after_domains_if_confidence_at_least": {"type": "number"},
    },
    "required": [
        "domains",
        "confidence",
        "execution_mode",
        "reasoning",
        "needs_web_fallback_if_low_confidence",
        "stop_after_domains_if_confidence_at_least",
    ],
    "additionalProperties": False,
}

BEDROCK_TOOL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "domain": {
            "type": "string",
            "enum": [
                "flood_damage",
                "fire_detection",
                "disaster_detection",
                "infrastructure",
                "stac",
            ],
        },
        "tool_steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "tool_name": {
                        "type": "string",
                        "enum": [
                            "geoserver_risk_mask_tool",
                            "flood_damage_city_tool",
                            "flood_depth_damage_tool",
                            "streamflow_forecast_tool",
                            "estimate_surface_water_ingress_tool",
                            "detect_fire_tool",
                            "query_disaster_events_tool",
                            "infrastructure_query_tool",
                            "get_route_info",
                            "query_stac_catalog",
                            "maxar_open_data_imagery_tool",
                        ],
                    },
                    "priority": {"type": "integer"},
                    "required_inputs": {"type": "array", "items": {"type": "string"}},
                    "parallel_group": {"type": "string"},
                    "args_template": {"type": "object", "additionalProperties": False},
                    "retry_policy": {
                        "type": "object",
                        "properties": {
                            "max_retries": {"type": "integer"},
                            "backoff": {
                                "type": "string",
                                "enum": ["none", "fixed", "exponential_jitter"],
                            },
                            "initial_delay_ms": {"type": "integer"},
                            "retry_on": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "timeout",
                                        "network_error",
                                        "http_429",
                                        "http_5xx",
                                        "empty_result",
                                    ],
                                },
                            },
                        },
                        "required": [
                            "max_retries",
                            "backoff",
                            "initial_delay_ms",
                            "retry_on",
                        ],
                        "additionalProperties": False,
                    },
                    "timeout_seconds": {"type": "integer"},
                    "on_failure": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["continue", "fallback_to_step", "abort_domain"],
                            },
                            "fallback_to_step_id": {"type": "string"},
                        },
                        "required": ["action", "fallback_to_step_id"],
                        "additionalProperties": False,
                    },
                    "success_weight": {"type": "number"},
                },
                "required": [
                    "step_id",
                    "tool_name",
                    "priority",
                    "required_inputs",
                    "parallel_group",
                    "args_template",
                    "retry_policy",
                    "timeout_seconds",
                    "on_failure",
                    "success_weight",
                ],
                "additionalProperties": False,
            },
        },
        "stop_policy": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["run_all", "stop_on_first_success", "stop_on_confidence"],
                },
                "confidence_threshold": {"type": "number"},
                "min_successful_steps": {"type": "integer"},
            },
            "required": ["mode", "confidence_threshold", "min_successful_steps"],
            "additionalProperties": False,
        },
        "reasoning": {"type": "string"},
    },
    "required": ["domain", "tool_steps", "stop_policy", "reasoning"],
    "additionalProperties": False,
}

BEDROCK_ARG_RESOLUTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "arguments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value_json": {"type": "string"},
                },
                "required": ["name", "value_json"],
                "additionalProperties": False,
            },
        },
        "covered_required_inputs": {"type": "array", "items": {"type": "string"}},
        "unresolved_required_inputs": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": [
        "arguments",
        "covered_required_inputs",
        "unresolved_required_inputs",
        "notes",
    ],
    "additionalProperties": False,
}

BEDROCK_FINAL_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "final_answer": {"type": "string"},
    },
    "required": ["final_answer"],
    "additionalProperties": False,
}

BEDROCK_LOCATION_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "place_query": {"type": "string"},
    },
    "required": ["place_query"],
    "additionalProperties": False,
}


@dataclass
class AgentCoreContext:
    task_id: str
    session_id: str
    user_id: str


class AgentCoreAdapter:
    """Minimal placeholder adapter.

    Replace internals with real agentcore-sdk calls.
    """

    class DomainRouteDecision(BaseModel):
        """Schema 1) Domain routing output (orchestrator-level)."""

        model_config = ConfigDict(extra="forbid")

        domains: list[RouteDomain] = Field(default_factory=list, min_length=1)
        confidence: float = Field(default=0.0, ge=0.0, le=1.0)
        execution_mode: ExecutionMode = "parallel"
        reasoning: str = ""
        needs_web_fallback_if_low_confidence: bool = True
        stop_after_domains_if_confidence_at_least: float = Field(
            default=0.8, ge=0.0, le=1.0
        )

    class RetryPolicy(BaseModel):
        """Retry policy for a tool step."""

        model_config = ConfigDict(extra="forbid")

        max_retries: int = Field(default=1, ge=0, le=5)
        backoff: BackoffMode = "fixed"
        initial_delay_ms: int = Field(default=300, ge=0)
        retry_on: list[RetryTrigger] = Field(
            default_factory=lambda: ["timeout", "network_error", "http_429", "http_5xx"]
        )

    class OnFailurePolicy(BaseModel):
        """Failure behavior per tool step."""

        model_config = ConfigDict(extra="forbid")

        action: FailureAction = "continue"
        fallback_to_step_id: str | None = None

    class StopPolicy(BaseModel):
        """Stop criteria for a domain tool plan."""

        model_config = ConfigDict(extra="forbid")

        mode: StopMode = "run_all"
        confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
        min_successful_steps: int = Field(default=1, ge=1)

    class ToolStepPlan(BaseModel):
        """Schema 2) Domain tool step plan item."""

        model_config = ConfigDict(extra="forbid")

        step_id: str
        tool_name: ToolName
        priority: int = Field(ge=1)
        required_inputs: list[str] = Field(default_factory=list)
        parallel_group: str | None = None
        args_template: dict[str, Any] = Field(default_factory=dict)
        retry_policy: "AgentCoreAdapter.RetryPolicy"
        timeout_seconds: int = Field(default=30, ge=1, le=120)
        on_failure: "AgentCoreAdapter.OnFailurePolicy"
        success_weight: float = Field(default=0.2, ge=0.0, le=1.0)

    class ToolPlan(BaseModel):
        """Schema 2) Domain tool plan output."""

        model_config = ConfigDict(extra="forbid")

        domain: DomainName
        tool_steps: list["AgentCoreAdapter.ToolStepPlan"] = Field(default_factory=list)
        stop_policy: "AgentCoreAdapter.StopPolicy"
        reasoning: str = ""

    class ToolStepExecution(BaseModel):
        """Schema 3) Policy engine step execution result."""

        model_config = ConfigDict(extra="forbid")

        step_id: str
        tool_name: ToolName
        status: Literal["done", "error", "skipped"]
        attempts: int = Field(ge=0)
        latency_ms: int = Field(ge=0)
        error_type: ErrorType | None = None
        error_message: str | None = None
        input_arguments: dict[str, Any] | None = None
        result: dict[str, Any] | None = None

    class ToolExecutionSummary(BaseModel):
        """Schema 3) Policy engine summary."""

        model_config = ConfigDict(extra="forbid")

        successful_steps: int = Field(default=0, ge=0)
        failed_steps: int = Field(default=0, ge=0)
        skipped_steps: int = Field(default=0, ge=0)
        domain_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
        fallback_triggered: bool = False

    class ToolExecutionResult(BaseModel):
        """Schema 3) Policy engine full output."""

        model_config = ConfigDict(extra="forbid")

        domain: DomainName
        steps: list["AgentCoreAdapter.ToolStepExecution"] = Field(default_factory=list)
        summary: "AgentCoreAdapter.ToolExecutionSummary"

    class ArgumentKV(BaseModel):
        model_config = ConfigDict(extra="forbid")

        name: str
        value_json: str

    class StepArgumentResolution(BaseModel):
        model_config = ConfigDict(extra="forbid")

        arguments: list["AgentCoreAdapter.ArgumentKV"] = Field(default_factory=list)
        covered_required_inputs: list[str] = Field(default_factory=list)
        unresolved_required_inputs: list[str] = Field(default_factory=list)
        notes: str = ""

    def __init__(self, route_decider: RouteDecider | None = None) -> None:
        cfg = self._load_runtime_config()
        self._agentcore_enabled = bool(cfg.agentcore_enabled)
        self._agentcore_region = cfg.agentcore_region
        self._agentcore_endpoint = (cfg.agentcore_endpoint or "").strip()
        self._agentcore_api_key = (cfg.agentcore_api_key or "").strip()
        self._router_model_id = (cfg.agentcore_router_model_id or "").strip()
        self._tool_planner_model_id = (cfg.agentcore_tool_planner_model_id or "").strip()
        self._agentcore_timeout_seconds = int(cfg.agentcore_timeout_seconds)
        self._agentcore_stage = cfg.agentcore_stage
        self._memory_id = (getattr(cfg, "agentcore_memory_id", "") or "").strip()
        self._memory_short_term_turns = int(
            getattr(cfg, "agentcore_memory_short_term_turns", 8) or 8
        )
        self._memory_long_term_top_k = int(
            getattr(cfg, "agentcore_memory_long_term_top_k", 5) or 5
        )

        # Optional AgentCore/LLM resolver. Should return a dict compatible
        # with DomainRouteDecision or a DomainRouteDecision instance.
        self._route_decider = route_decider
        self._client = self._init_agentcore_client()
        self._last_bedrock_failure_reason = ""
        self._tool_meta_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _load_runtime_config() -> Any:
        module = importlib.import_module("eo_llm.config")
        return module.get_config()

    def _init_agentcore_client(self) -> Any | None:
        """Initialize AgentCore client when configuration is available.

        Placeholder implementation:
        - returns None when integration is disabled or boto3 isn't available
        - uses AWS default credential chain (env/profile/role)
        """
        if not self._agentcore_enabled:
            return None

        try:
            import boto3
        except Exception:
            return None

        kwargs: dict[str, Any] = {"region_name": self._agentcore_region}
        if self._agentcore_endpoint:
            kwargs["endpoint_url"] = self._agentcore_endpoint
        try:
            return boto3.client("bedrock-runtime", **kwargs)
        except Exception:
            return None

    def is_ready(self) -> bool:
        """True when AgentCore is enabled and client initialization succeeded."""
        return bool(self._agentcore_enabled and self._client is not None)

    @staticmethod
    def _event_role_to_chat_role(value: str) -> str:
        v = (value or "").upper()
        if v == "ASSISTANT":
            return "assistant"
        if v == "USER":
            return "user"
        if v == "TOOL":
            return "tool"
        return "assistant"

    @staticmethod
    def _coerce_record_text(record: Any) -> str:
        if record is None:
            return ""
        content = record.get("content") if hasattr(record, "get") else None
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            if content:
                return json.dumps(content, ensure_ascii=True)[:800]
        if hasattr(record, "get"):
            summary = record.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
        return ""

    @staticmethod
    def _render_namespace_template(
        template: str,
        *,
        actor_id: str,
        session_id: str,
        strategy_id: str,
    ) -> str | None:
        if not isinstance(template, str) or not template.strip():
            return None
        ns = template
        ns = ns.replace("{actorId}", actor_id)
        ns = ns.replace("{sessionId}", session_id)
        if strategy_id:
            ns = ns.replace("{memoryStrategyId}", strategy_id)
        if "{" in ns or "}" in ns:
            return None
        return ns


    def route_domains(self, *, query: str) -> DomainRouteDecision:
        q = (query or "").strip().lower()
        if not q:
            return self.DomainRouteDecision(
                domains=["websearch_only"],
                confidence=1.0,
                execution_mode="sequential",
                reasoning="Empty query fallback.",
            )

        if self._route_decider is not None:
            raw = self._route_decider(q)
            if raw is not None:
                return (
                    raw
                    if isinstance(raw, self.DomainRouteDecision)
                    else self.DomainRouteDecision.model_validate(raw)
                )

        if self.is_ready() and self._router_model_id:
            system_prompt = (
                "You are a routing policy engine. Return only data that conforms to the provided JSON schema."
            )
            user_prompt = (
                "Route this query to one or more domains from: "
                "flood_damage, fire_detection, disaster_detection, infrastructure, stac, document_qa, tools_info, websearch_only.\n"
                "Rules:\n"
                "- Prefer specific domain(s) when clear.\n"
                "- Use websearch_only only when none fit.\n"
                "- Use tools_info when the user asks what tools/capabilities are available, how a tool works, what data sources a tool uses, or what questions they can ask.\n"
                "- Do NOT use tools_info for greetings, thanks, or other casual chat.\n"
                "- Use document_qa when user asks about the uploaded/attached document contents.\n"
                "- Streamflow/river discharge/water-level forecast requests belong to flood_damage.\n"
                "- STAC is for satellite catalog/discovery/imagery tasks, not hydrological forecasts.\n"
                "- CLMS burnt-area impact requests belong to fire_detection.\n"
                "- CLMS land-cover exposure and CEMS rapid-mapping requests belong to disaster_detection.\n"
                "- confidence in [0,1].\n"
                "- execution_mode is parallel or sequential.\n"
                f"Query: {q}\n"
                "Follow the schema exactly."
            )
            raw = self._call_bedrock_json(
                model_id=self._router_model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_schema=BEDROCK_ROUTE_SCHEMA,
                schema_name="domain_route_decision",
                schema_description="Routing decision for EO_LLM orchestrator",
                max_tokens=500,
            )
            if raw is not None:
                try:
                    decision = self.DomainRouteDecision.model_validate(raw)
                    return decision
                except Exception:
                    raise RuntimeError(
                        "AgentCore route_domains schema validation failed."
                    ) from None

            raise RuntimeError(
                "AgentCore route_domains Bedrock call returned no valid schema output. "
                f"Reason: {self._last_bedrock_failure_reason or 'unknown'}"
            )

        raise RuntimeError(
            "AgentCore route_domains unavailable: no route decider and Bedrock client/model not ready."
        )

    def select_tool_plan(self, *, domain: DomainName, query: str = "") -> ToolPlan:
        tools = DOMAIN_TOOLS.get(domain, [])
        if self.is_ready() and self._tool_planner_model_id and tools:
            system_prompt = (
                "You are a domain tool planner. Return only data that conforms to the provided JSON schema."
            )
            user_prompt = (
                f"Domain: {domain}\n"
                f"Allowed tools: {', '.join(tools)}\n"
                f"User query: {(query or '').strip()}\n"
                "Build a concise tool plan with 1-4 steps.\n"
                "Rules:\n"
                "- tool_name must be from allowed tools.\n"
                "- Use supported enums exactly (no synonyms).\n"
                "- Prefer practical required_inputs that match runtime data availability.\n"
                "- If the query asks for streamflow forecast/discharge, prioritize streamflow_forecast_tool when available.\n"
                "- In fire_detection, if query mentions burnt area/burned area/zone brulee/zone brulee CLMS, prioritize clms_burnt_area_impact_tool.\n"
                "Follow the schema exactly."
            )
            raw = self._call_bedrock_json(
                model_id=self._tool_planner_model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_schema=BEDROCK_TOOL_PLAN_SCHEMA,
                schema_name="domain_tool_plan",
                schema_description="Execution plan for a single EO_LLM domain agent",
                max_tokens=1200,
            )
            if raw is not None:
                try:
                    candidate = self.ToolPlan.model_validate(raw)
                    if candidate.domain == domain and all(
                        step.tool_name in tools for step in candidate.tool_steps
                    ):
                        return candidate
                    raise RuntimeError(
                        f"AgentCore select_tool_plan returned invalid domain/tools for {domain}."
                    )
                except Exception:
                    raise RuntimeError(
                        f"AgentCore select_tool_plan schema validation failed for {domain}."
                    ) from None

            raise RuntimeError(
                "AgentCore select_tool_plan Bedrock call returned no valid schema output "
                f"for {domain}. Reason: {self._last_bedrock_failure_reason or 'unknown'}"
            )

        raise RuntimeError(
            f"AgentCore select_tool_plan unavailable for {domain}: Bedrock client/model not ready."
        )

    def compose_final_answer(
        self,
        *,
        query: str,
        answer_source: str,
        aggregated_evidence: str,
        domain_results: dict[str, Any] | None = None,
        web_results: list[dict[str, Any]] | None = None,
    ) -> str:
        """Use Bedrock structured output to compose user-facing final answer."""
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            raise RuntimeError("AgentCore finalizer unavailable: Bedrock model/client not ready.")

        domain_json = json.dumps(domain_results or {}, ensure_ascii=True, default=str)
        web_json = json.dumps(web_results or [], ensure_ascii=True, default=str)
        # Keep prompt bounded to avoid token bloat on large traces.
        if len(domain_json) > 6000:
            domain_json = domain_json[:6000] + "...(truncated)"
        if len(web_json) > 2500:
            web_json = web_json[:2500] + "...(truncated)"

        today_utc = datetime.now(timezone.utc).date().isoformat()
        system_prompt = (
            "You are an EO risk analysis assistant. "
            "Compose a concise, factual final answer from provided evidence only. "
            "If evidence is limited or conflicting, explicitly say so. "
            "Never contradict successful tool outputs. "
            "Never claim a date is in the future unless it is strictly later than today's date."
        )
        user_prompt = (
            f"Today (UTC): {today_utc}\n"
            f"User query: {query}\n"
            f"Answer source selected by pipeline: {answer_source}\n"
            f"Aggregated evidence summary: {aggregated_evidence}\n"
            f"Domain results JSON: {domain_json}\n"
            f"Web results JSON: {web_json}\n"
            "Write a helpful final answer in plain text with:\n"
            "- 1 short direct answer paragraph\n"
            "- 2-5 concise bullet points with key findings or caveats\n"
            "- mention uncertainty when tools failed or evidence is partial\n"
            "Return only data conforming to the schema."
        )
        raw = self._call_bedrock_json(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=BEDROCK_FINAL_ANSWER_SCHEMA,
            schema_name="final_answer_response",
            schema_description="Final user-facing answer text",
            max_tokens=900,
        )
        if raw is None:
            raise RuntimeError(
                "AgentCore compose_final_answer returned no valid schema output. "
                f"Reason: {self._last_bedrock_failure_reason or 'unknown'}"
            )
        final_answer = str(raw.get("final_answer") or "").strip()
        if not final_answer:
            raise RuntimeError("AgentCore compose_final_answer returned empty answer.")
        return final_answer

    def extract_location_hint(self, *, query: str) -> str:
        """Extract a concise geocodable place string from user query."""
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            return ""
        raw = self._call_bedrock_json(
            model_id=model_id,
            system_prompt=(
                "Extract only the most relevant place name from user query for geocoding. "
                "Return empty string if no location is present."
            ),
            user_prompt=(
                f"Query: {query}\n"
                "Examples:\n"
                "- 'fires in paris in 2025' -> 'Paris, France'\n"
                "- 'storms in spain 2015-2025' -> 'Spain'\n"
                "- 'hello' -> ''\n"
                "Return only schema-conformant JSON."
            ),
            json_schema=BEDROCK_LOCATION_EXTRACT_SCHEMA,
            schema_name="location_hint",
            schema_description="Geocodable place extracted from user query",
            max_tokens=120,
        )
        if raw is None:
            return ""
        return str(raw.get("place_query") or "").strip()

    def answer_question_with_document(
        self, *, query: str, document_ref: dict[str, Any]
    ) -> dict[str, Any]:
        """Answer a user question grounded in one uploaded document."""
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            raise RuntimeError("AgentCore document QA unavailable: Bedrock model/client not ready.")
        doc_bytes = load_document_bytes(document_ref)
        if not doc_bytes:
            raise ValueError("Uploaded document is empty.")
        assert self._client is not None

        neutral_name = str(document_ref.get("neutral_name") or "Uploaded Document").strip()
        format_value = str(document_ref.get("format") or "pdf").strip().lower() or "pdf"
        response = self._client.converse(
            modelId=model_id,
            system=[
                {
                    "text": (
                        "You answer questions using only the provided document. "
                        "If the answer is not present, say so clearly."
                    )
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": (query or "").strip() or "Summarize this document."},
                        {
                            "document": {
                                "format": format_value,
                                "name": neutral_name,
                                "source": {"bytes": doc_bytes},
                            }
                        },
                    ],
                }
            ],
            inferenceConfig={"temperature": 0.0, "maxTokens": 900},
        )
        text = self._extract_text_from_converse_response(response)
        citations = self._extract_document_citations(response)
        return {"answer": text, "citations": citations}

    def extract_location_from_document(
        self, *, query: str, document_ref: dict[str, Any]
    ) -> str:
        """Resolve an implicit place reference from uploaded document context."""
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            return ""
        try:
            doc_bytes = load_document_bytes(document_ref)
        except Exception:
            return ""
        neutral_name = str(document_ref.get("neutral_name") or "Uploaded Document").strip()
        format_value = str(document_ref.get("format") or "pdf").strip().lower() or "pdf"
        raw = self._call_bedrock_json(
            model_id=model_id,
            system_prompt=(
                "Extract a single geocodable place from the document relevant to the user query. "
                "Return empty string if no clear location is present."
            ),
            user_prompt=(
                f"User query: {query}\n"
                "Return one place only (city/region/country), suitable for geocoding."
            ),
            json_schema=BEDROCK_LOCATION_EXTRACT_SCHEMA,
            schema_name="document_location_hint",
            schema_description="Location inferred from uploaded document and query",
            max_tokens=120,
            user_content=[
                {"text": f"User query: {query}"},
                {
                    "document": {
                        "format": format_value,
                        "name": neutral_name,
                        "source": {"bytes": doc_bytes},
                    }
                },
            ],
        )
        if raw is None:
            return ""
        return str(raw.get("place_query") or "").strip()

    def execute_tool_plan(
        self,
        *,
        plan: ToolPlan,
        runtime_args_by_tool: dict[str, dict[str, Any]],
        tool_caller: Callable[[str, dict[str, Any]], dict[str, Any]],
        execution_context: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        ordered_steps = sorted(plan.tool_steps, key=lambda s: s.priority)
        index_by_step_id = {step.step_id: idx for idx, step in enumerate(ordered_steps)}
        executions: list[AgentCoreAdapter.ToolStepExecution] = []
        success_count = 0
        fail_count = 0
        skip_count = 0
        success_weight_sum = 0.0
        total_weight = sum(step.success_weight for step in ordered_steps) or 1.0
        fallback_triggered = False

        i = 0
        while i < len(ordered_steps):
            step = ordered_steps[i]
            merged_args = dict(step.args_template)
            merged_args.update(runtime_args_by_tool.get(step.tool_name, {}))
            resolution = self._resolve_step_arguments(
                plan=plan,
                step=step,
                candidate_args=merged_args,
                execution_context=execution_context or {},
            )
            merged_args = resolution["arguments"]
            missing = list(resolution["missing"])
            if missing:
                skip_count += 1
                executions.append(
                    self.ToolStepExecution(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        status="skipped",
                        attempts=0,
                        latency_ms=0,
                        error_type="validation_error",
                        error_message=f"Missing required inputs: {', '.join(missing)}",
                        input_arguments=merged_args,
                        result=None,
                    )
                )
                i = self._next_step_index_after_failure(
                    current_index=i,
                    step=step,
                    index_by_step_id=index_by_step_id,
                )
                continue

            attempts = 0
            last_err = ""
            last_error_type: ErrorType | None = None
            last_result: dict[str, Any] | None = None
            latency_ms = 0
            max_attempts = max(1, step.retry_policy.max_retries + 1)
            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                t0 = time.perf_counter()
                last_result = tool_caller(step.tool_name, merged_args)
                latency_ms += int((time.perf_counter() - t0) * 1000)
                if not bool(last_result.get("error")):
                    success_count += 1
                    success_weight_sum += step.success_weight
                    executions.append(
                        self.ToolStepExecution(
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            status="done",
                            attempts=attempts,
                            latency_ms=latency_ms,
                            input_arguments=merged_args,
                            result=last_result,
                        )
                    )
                    break

                last_err = str(last_result.get("message") or "Tool execution failed")
                last_error_type = self._infer_error_type(last_result, last_err)
                can_retry = (
                    attempt < max_attempts
                    and step.retry_policy.backoff != "none"
                    and self._should_retry(last_error_type, step.retry_policy.retry_on)
                )
                if can_retry:
                    delay_ms = self._compute_backoff_ms(step.retry_policy, attempt)
                    if delay_ms > 0:
                        time.sleep(delay_ms / 1000.0)

            else:
                fail_count += 1
                executions.append(
                    self.ToolStepExecution(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        status="error",
                        attempts=attempts,
                        latency_ms=latency_ms,
                        error_type=last_error_type or "unknown",
                        error_message=last_err,
                        input_arguments=merged_args,
                        result=last_result,
                    )
                )

            domain_confidence = min(1.0, success_weight_sum / total_weight)
            if self._should_stop(plan.stop_policy, success_count, domain_confidence):
                break
            if executions and executions[-1].status == "error":
                next_index = self._next_step_index_after_failure(
                    current_index=i,
                    step=step,
                    index_by_step_id=index_by_step_id,
                )
                fallback_triggered = fallback_triggered or next_index != (i + 1)
                if step.on_failure.action == "abort_domain":
                    break
                i = next_index
                continue
            i += 1

        domain_confidence = min(1.0, success_weight_sum / total_weight)

        return self.ToolExecutionResult(
            domain=plan.domain,
            steps=executions,
            summary=self.ToolExecutionSummary(
                successful_steps=success_count,
                failed_steps=fail_count,
                skipped_steps=skip_count,
                domain_confidence=domain_confidence,
                fallback_triggered=fallback_triggered or (fail_count > 0 and success_count > 0),
            ),
        )

    def _resolve_step_arguments(
        self,
        *,
        plan: ToolPlan,
        step: ToolStepPlan,
        candidate_args: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        tool_meta = self._tool_signature_metadata(step.tool_name)
        tool_param_names = list(tool_meta.get("all_params") or [])
        required_params = list(tool_meta.get("required_params") or [])
        docstring = str(tool_meta.get("docstring") or "")

        # Prefer dynamic AgentCore resolution so conceptual required_inputs
        # map to real tool arguments without brittle key matching.
        #
        # IMPORTANT: only use the LLM resolver when we actually know the tool's
        # parameter names. Without signature metadata (the MCP tools are a
        # separate service here, so `eo_llm.mcp_server.tools` is not importable)
        # the resolver would be told the set of allowed argument names is empty
        # and return zero arguments, discarding the deterministic runtime args
        # the domain node already built. In that case fall through to the
        # deterministic pass-through below.
        if self.is_ready() and self._tool_planner_model_id and tool_param_names:
            today_utc = datetime.now(timezone.utc).date().isoformat()
            prompt = (
                f"Today (UTC): {today_utc}\n"
                f"Domain: {plan.domain}\n"
                f"Tool: {step.tool_name}\n"
                f"Required inputs (conceptual): {json.dumps(step.required_inputs)}\n"
                f"Allowed argument names: {json.dumps(tool_param_names)}\n"
                f"Required argument names (from signature): {json.dumps(required_params)}\n"
                f"Tool docstring: {docstring[:1200]}\n"
                f"Candidate arguments: {json.dumps(candidate_args, default=str)}\n"
                f"Execution context: {json.dumps(execution_context, default=str)}\n"
                "Return arguments ready for tool execution.\n"
                "Rules:\n"
                "- Use only allowed argument names.\n"
                "- Keep values as JSON strings in value_json.\n"
                "- Resolve conceptual inputs to concrete args when possible.\n"
                "- Ensure required argument names are present with valid values.\n"
                "- If a required argument is missing, infer a safe value from context/docstring.\n"
                "- Derive date/time arguments (e.g. start_date, end_date, year, month) "
                "from the user query in 'Execution context'; format dates as YYYY-MM-DD.\n"
                "- When the query specifies a time period, OVERRIDE any candidate/default "
                "date values (including a hardcoded current year) to match the query.\n"
                "- Only keep candidate/default date values when the query has no temporal reference.\n"
                "- Put unresolved conceptual inputs in unresolved_required_inputs.\n"
                "Follow the schema exactly."
            )
            raw = self._call_bedrock_json(
                model_id=self._tool_planner_model_id,
                system_prompt=(
                    "You are an argument-resolution policy engine for tool execution. "
                    "Output strictly to schema."
                ),
                user_prompt=prompt,
                json_schema=BEDROCK_ARG_RESOLUTION_SCHEMA,
                schema_name="step_argument_resolution",
                schema_description="Resolved concrete arguments for one tool step",
                max_tokens=900,
            )
            if raw is not None:
                try:
                    parsed = self.StepArgumentResolution.model_validate(raw)
                    resolved_args: dict[str, Any] = {}
                    for item in parsed.arguments:
                        if tool_param_names and item.name not in tool_param_names:
                            continue
                        try:
                            resolved_args[item.name] = json.loads(item.value_json)
                        except Exception:
                            resolved_args[item.name] = item.value_json
                    # Merge resolver output over the node-provided candidate args
                    # so deterministic values (e.g. lat/lon) are preserved while
                    # the resolver fills/overrides date-like args from the query.
                    merged = {
                        k: v
                        for k, v in candidate_args.items()
                        if not tool_param_names or k in tool_param_names
                    }
                    merged.update(resolved_args)
                    missing = [x for x in parsed.unresolved_required_inputs if x]
                    return {"arguments": merged, "missing": missing}
                except Exception:
                    pass

        # Deterministic pass-through of the node-provided runtime arguments.
        # Only flag missing inputs when we actually know the tool signature;
        # otherwise trust the domain node's args and let the tool validate,
        # rather than wrongly skipping the step on conceptual key mismatches.
        if tool_param_names:
            missing = [
                key
                for key in step.required_inputs
                if key in tool_param_names
                and (candidate_args.get(key) is None or candidate_args.get(key) == "")
            ]
        else:
            missing = []
        return {"arguments": candidate_args, "missing": missing}

    def _tool_signature_metadata(self, tool_name: str) -> dict[str, Any]:
        cached = self._tool_meta_cache.get(tool_name)
        if cached is not None:
            return cached

        meta: dict[str, Any] = {
            "all_params": [],
            "required_params": [],
            "docstring": "",
        }

        # Primary source: the MCP server's advertised tool schemas. The MCP
        # tools run as a separate service, so we cannot import them locally;
        # `list_tools` gives us the parameter names, required fields, and
        # docstrings the argument resolver needs (e.g. to map query dates to
        # start_date/end_date/year).
        try:
            from eo_llm.adapters.mcp_client import get_tool_metadata

            fetched = get_tool_metadata(tool_name)
            if fetched and fetched.get("all_params"):
                meta = {
                    "all_params": list(fetched.get("all_params") or []),
                    "required_params": list(fetched.get("required_params") or []),
                    "docstring": str(fetched.get("docstring") or ""),
                }
                self._tool_meta_cache[tool_name] = meta
                return meta
        except Exception:
            pass

        # Fallback: try to import a local tools package (used when the graph and
        # tools live in the same package, e.g. the original EO_LLM layout).
        try:
            tools_pkg = importlib.import_module("eo_llm.mcp_server.tools")
            pkg_path = getattr(tools_pkg, "__path__", None)
            if pkg_path is None:
                self._tool_meta_cache[tool_name] = meta
                return meta
            for mod in pkgutil.iter_modules(pkg_path):
                module_name = f"{tools_pkg.__name__}.{mod.name}"
                try:
                    module = importlib.import_module(module_name)
                except Exception:
                    continue
                fn = getattr(module, tool_name, None)
                if not callable(fn):
                    continue
                sig = inspect.signature(fn)
                all_params: list[str] = []
                required_params: list[str] = []
                for p in sig.parameters.values():
                    if p.kind in (
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    ):
                        all_params.append(p.name)
                        if p.default is inspect._empty:
                            required_params.append(p.name)
                meta = {
                    "all_params": all_params,
                    "required_params": required_params,
                    "docstring": inspect.getdoc(fn) or "",
                }
                break
        except Exception:
            meta = {"all_params": [], "required_params": [], "docstring": ""}

        self._tool_meta_cache[tool_name] = meta
        return meta

    def _call_bedrock_json(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        schema_name: str,
        schema_description: str,
        temperature: float = 0.0,
        max_tokens: int = 800,
        user_content: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Call Bedrock Converse with structured outputs and parse a JSON object response."""
        if not self._client or not model_id:
            self._last_bedrock_failure_reason = "client_or_model_not_ready"
            return None
        self._last_bedrock_failure_reason = ""
        try:
            response = self._client.converse(
                modelId=model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": user_content or [{"text": user_prompt}],
                    }
                ],
                inferenceConfig={
                    "temperature": float(temperature),
                    "maxTokens": int(max_tokens),
                },
                outputConfig={
                    "textFormat": {
                        "type": "json_schema",
                        "structure": {
                            "jsonSchema": {
                                "name": schema_name,
                                "description": schema_description,
                                "schema": json.dumps(json_schema),
                            }
                        },
                    }
                },
            )
            stop_reason = str(response.get("stopReason") or "").lower()
            if stop_reason in {"max_tokens", "guardrail_intervened", "content_filtered"}:
                self._last_bedrock_failure_reason = f"stop_reason:{stop_reason}"
                logger.warning(
                    "Bedrock %s call unusable (model=%s): stop_reason=%s",
                    schema_name,
                    model_id,
                    stop_reason,
                )
                return None
            content = (
                response.get("output", {})
                .get("message", {})
                .get("content", [])
            )
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            text = "\n".join(text_parts).strip()
            parsed = self._parse_json_object_from_text(text)
            if parsed is None:
                self._last_bedrock_failure_reason = "json_parse_failed"
                logger.warning(
                    "Bedrock %s call returned unparseable text (model=%s): %s",
                    schema_name,
                    model_id,
                    (text or "")[:300],
                )
            return parsed
        except Exception as e:
            self._last_bedrock_failure_reason = f"{type(e).__name__}:{e}"
            logger.warning(
                "Bedrock %s call failed (model=%s): %s: %s",
                schema_name,
                model_id,
                type(e).__name__,
                str(e)[:500],
            )
            return None

    @staticmethod
    def _extract_text_from_converse_response(response: dict[str, Any]) -> str:
        content = (
            response.get("output", {})
            .get("message", {})
            .get("content", [])
        )
        if not isinstance(content, list):
            return ""
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
            citations_block = part.get("citationsContent")
            if isinstance(citations_block, dict):
                generated = citations_block.get("content")
                if isinstance(generated, list):
                    for item in generated:
                        if isinstance(item, dict):
                            t = item.get("text")
                            if isinstance(t, str) and t.strip():
                                text_parts.append(t.strip())
        return "\n".join(text_parts).strip()

    @staticmethod
    def _extract_document_citations(response: dict[str, Any]) -> list[dict[str, Any]]:
        content = (
            response.get("output", {})
            .get("message", {})
            .get("content", [])
        )
        if not isinstance(content, list):
            return []
        citations: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            citations_block = part.get("citationsContent")
            if not isinstance(citations_block, dict):
                continue
            refs = citations_block.get("citations")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, dict):
                    citations.append(ref)
        return citations

    @staticmethod
    def _parse_json_object_from_text(text: str) -> dict[str, Any] | None:
        """Extract and parse the first JSON object found in text."""
        if not text:
            return None

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        end = -1
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end <= start:
            return None
        candidate = text[start:end]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    @staticmethod
    def _compute_backoff_ms(retry_policy: RetryPolicy, attempt: int) -> int:
        base_ms = max(0, retry_policy.initial_delay_ms)
        if retry_policy.backoff == "fixed":
            return base_ms
        if retry_policy.backoff == "exponential_jitter":
            exp_ms = base_ms * (2 ** max(0, attempt - 1))
            jitter = random.randint(0, max(1, exp_ms // 3))
            return exp_ms + jitter
        return 0

    @staticmethod
    def _should_retry(error_type: ErrorType | None, retry_on: list[RetryTrigger]) -> bool:
        return bool(error_type and error_type in retry_on)

    @staticmethod
    def _infer_error_type(result: dict[str, Any] | None, message: str) -> ErrorType:
        msg = (message or "").lower()
        if "timeout" in msg:
            return "timeout"
        if "429" in msg or "rate limit" in msg:
            return "http_429"
        if any(x in msg for x in ("500", "502", "503", "504", "server error")):
            return "http_5xx"
        if any(x in msg for x in ("connection", "network", "dns", "ssl", "refused")):
            return "network_error"
        if "missing required inputs" in msg or "validation" in msg:
            return "validation_error"
        if result is not None and not result.get("error") and not result.get("data"):
            return "empty_result"
        return "unknown"

    @staticmethod
    def _should_stop(stop_policy: StopPolicy, success_count: int, confidence: float) -> bool:
        if stop_policy.mode == "run_all":
            return False
        if stop_policy.mode == "stop_on_first_success":
            return success_count >= max(1, stop_policy.min_successful_steps)
        if stop_policy.mode == "stop_on_confidence":
            return confidence >= stop_policy.confidence_threshold
        return False

    @staticmethod
    def _next_step_index_after_failure(
        *,
        current_index: int,
        step: ToolStepPlan,
        index_by_step_id: dict[str, int],
    ) -> int:
        if step.on_failure.action != "fallback_to_step":
            return current_index + 1
        fallback_step_id = step.on_failure.fallback_to_step_id
        if not fallback_step_id:
            return current_index + 1
        fallback_idx = index_by_step_id.get(fallback_step_id)
        if fallback_idx is None:
            return current_index + 1
        return fallback_idx
