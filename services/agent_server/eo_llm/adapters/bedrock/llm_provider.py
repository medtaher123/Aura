"""LLM provider protocol for Bedrock-backed graph operations."""

from __future__ import annotations

from typing import Any, Iterator, Protocol, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Interface for LLM communications."""

    @property
    def last_failure_reason(self) -> str: ...

    def call_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        schema_name: str,
        schema_description: str,
        temperature: float = 0.0,
        max_tokens: int = 800,
        user_content: list[dict[str, Any]] | None = None,
    ) -> T | None: ...

    def call_stream(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> Iterator[str]: ...

    def call_standard_with_document(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        document_bytes: bytes,
        document_name: str,
        document_format: str,
    ) -> dict[str, Any]: ...
