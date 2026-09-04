"""Agentic domain loop: LLM calls tools until it produces a final answer."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.adapters.bedrock.chat_history_context import get_chat_history
from eo_llm.adapters.bedrock.llm_model_router import LLMModelRouter
from eo_llm.adapters.bedrock.llm_provider import AgentToolCallRecord, ConverseToolCall
from src.core.event_emitter import DataAgentStepEvent, emit_event
from src.tools.contracts import ToolArtifacts, ToolResponse
from src.tools.runtime.gateway import get_tool_gateway


class DomainAgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    message: str = ""
    tool_calls: list[AgentToolCallRecord] = Field(default_factory=list)
    paused: bool = False
    needs_input: dict[str, Any] | None = None
    error: bool = False


class DomainToolAgent:
    """Run an LLM ↔ tool loop until a final answer or a user-input pause."""

    def __init__(self, *, max_rounds: int = 10) -> None:
        self._max_rounds = max(1, int(max_rounds))

    async def run(
        self,
        *,
        domain: str,
        allowed_tools: list[str],
        system_prompt: str,
        runtime_args_by_tool: dict[str, dict[str, Any]] | None = None,
        execution_context: dict[str, Any] | None = None,
        tool_call_records: list[AgentToolCallRecord] | None = None,
    ) -> DomainAgentRunResult:
        runtime_args_by_tool = runtime_args_by_tool or {}
        execution_context = execution_context or {}

        gateway = get_tool_gateway()
        allowed = set(allowed_tools)
        tools = gateway.list_tools(allowed_names=allowed)
        if not tools:
            return DomainAgentRunResult(
                domain=domain,
                message="No tools available for this domain.",
                error=True,
            )

        records: list[AgentToolCallRecord] = list(tool_call_records or [])

        for turn_index in range(self._max_rounds):
            history = list(get_chat_history() or ())
            for record in records:
                history.extend(record.to_messages())
            turn = await LLMModelRouter().call_converse(
                system_prompt=system_prompt,
                chat_history=history,
                tools=tools,
            )

            if turn.stop_reason != "tool_use":
                return DomainAgentRunResult(
                    domain=domain,
                    message=turn.text or "Done.",
                    tool_calls=records,
                )

            if not turn.tool_calls:
                return DomainAgentRunResult(
                    domain=domain,
                    message=turn.text or "No tool calls produced.",
                    tool_calls=records,
                    error=True,
                )

            for call in turn.tool_calls:
                record = await self._invoke_tool(
                    call=call,
                    turn_index=turn_index,
                    allowed=allowed,
                    runtime_args_by_tool=runtime_args_by_tool,
                    gateway=gateway,
                    domain=domain,
                    execution_context=execution_context,
                )
                records.append(record)
                if record.result and self._pause_needs(record.result):
                    return DomainAgentRunResult(
                        domain=domain,
                        message=record.result.message or "Additional input required.",
                        tool_calls=records,
                        paused=True,
                        needs_input=dict(record.result.data.get("needs_input") or {}),
                    )

        return DomainAgentRunResult(
            domain=domain,
            message=(
                f"Stopped after {self._max_rounds} tool rounds without a final answer."
            ),
            tool_calls=records,
            error=True,
        )

    async def _invoke_tool(
        self,
        *,
        call: ConverseToolCall,
        turn_index: int,
        allowed: set[str],
        runtime_args_by_tool: dict[str, dict[str, Any]],
        gateway: Any,
        domain: str,
        execution_context: dict[str, Any],
    ) -> AgentToolCallRecord:
        tool_name = call.name
        arguments = dict(call.arguments or {})

        if tool_name not in allowed:
            return AgentToolCallRecord(
                tool_use_id=call.id,
                turn_index=turn_index,
                tool_name=tool_name or "unknown",
                arguments=arguments,
                status="error",
                error_message=f"Tool not allowed for domain: {tool_name}",
            )

        merged_args = dict(runtime_args_by_tool.get(tool_name) or {})
        merged_args.update(arguments)
        self._emit_running(
            tool_name=tool_name,
            args=merged_args,
            domain=domain,
            execution_context=execution_context,
        )

        t0 = time.perf_counter()
        result = await gateway.invoke(tool_name, merged_args)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        record = AgentToolCallRecord(
            tool_use_id=call.id,
            turn_index=turn_index,
            tool_name=tool_name,
            arguments=merged_args,
            status="error" if result.error else "done",
            latency_ms=latency_ms,
            result=result,
            error_message=result.message if result.error else None,
        )
        self._emit_done(
            tool_name=tool_name,
            args=merged_args,
            record=record,
            domain=domain,
            execution_context=execution_context,
        )
        return record

    @staticmethod
    def _pause_needs(result: ToolResponse) -> bool:
        data = result.data or {}
        needs_input = data.get("needs_input")
        return bool(
            data.get("stopped_for_user_input")
            and isinstance(needs_input, dict)
            and needs_input
        )

    @staticmethod
    def _emit_running(
        *,
        tool_name: str,
        args: dict[str, Any],
        domain: str,
        execution_context: dict[str, Any],
    ) -> None:
        emit_event(
            DataAgentStepEvent(
                phase="running",
                tool_name=tool_name,
                tool_input=args,
                domain=domain or execution_context.get("domain"),
            )
        )

    @staticmethod
    def _emit_done(
        *,
        tool_name: str,
        args: dict[str, Any],
        record: AgentToolCallRecord,
        domain: str,
        execution_context: dict[str, Any],
    ) -> None:
        result = record.result
        observation = (
            result.message if result is not None else (record.error_message or "")
        )
        artifacts = result.artifacts if result is not None else ToolArtifacts()
        result_payload = (
            result.model_dump(mode="python") if result is not None else None
        )
        emit_event(
            DataAgentStepEvent(
                phase="done",
                tool_name=tool_name,
                tool_input=args,
                domain=domain or execution_context.get("domain"),
                status=record.status,
                attempts=1,
                execution_time_seconds=round(record.latency_ms / 1000.0, 3),
                observation=observation,
                error=record.status != "done",
                artifacts=artifacts,
                result=result_payload,
            )
        )
