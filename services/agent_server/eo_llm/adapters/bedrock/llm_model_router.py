from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
import importlib
import inspect
import pkgutil
from typing import Any, AsyncIterator, Type, TypeVar

from pydantic import BaseModel

from eo_llm.adapters.bedrock.llm_provider import (
    AgentToolCallRecord,
    ConverseResponse,
    FileMediaMode,
    LLMProvider,
)
from src.config import get_config
from src.core.singleton_meta import SingletonMeta
from src.db.models.message import Message
from src.tools.providers.base import ToolDescriptor


class TaskType(Enum):
    FAST = "fast"               # High speed, low cost (e.g., basic summarization)
    REASONING = "reasoning"     # Complex logic, coding, deep analysis
    STRUCTURED = "structured"   # Strict adherence to JSON/Pydantic schemas
    DOCUMENT = "document"       # Multimodal or heavy RAG workloads

@dataclass
class LLMRoute:
    provider: LLMProvider
    model_id: str


T = TypeVar("T", bound=BaseModel)

config = get_config()

class LLMModelRouter(metaclass=SingletonMeta):

    def __init__(self):

        self.providers = {}
        
        self._auto_register_providers("eo_llm.adapters.bedrock.llm_providers")

        self._routes = {
            TaskType.FAST: LLMRoute(
                provider=self._get_provider(config.fast_llm_provider),
                model_id=config.fast_llm_model_id
            ),
            TaskType.REASONING: LLMRoute(
                provider=self._get_provider(config.reasoning_llm_provider), 
                model_id=config.reasoning_llm_model_id
            ),
            TaskType.STRUCTURED: LLMRoute(
                provider=self._get_provider(config.structured_llm_provider), 
                model_id=config.structured_llm_model_id
            ),
            TaskType.DOCUMENT: LLMRoute(
                provider=self._get_provider(config.document_llm_provider), 
                model_id=config.document_llm_model_id
            ),
        }
        

    def _auto_register_providers(self, package_name: str):
        """Scans a package and registers all valid LLMProvider subclasses."""
        try:
            package = importlib.import_module(package_name)
        except ImportError as e:
            raise ImportError(f"Could not import package {package_name}. Make sure it has an __init__.py") from e

        # Walk through all modules inside the llm_provider package
        for _, module_name, is_pkg in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            module = importlib.import_module(module_name)
            
            # Inspect the module for classes
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Check if it's a subclass of LLMProvider, but NOT the abstract base class itself
                if issubclass(obj, LLMProvider) and obj is not LLMProvider:
                    # Ensure we aren't instantiating a partially implemented abstract class
                    if not inspect.isabstract(obj):
                        try:
                            # Instantiate the provider and register it
                            provider_instance = obj()
                            self._register_provider(provider_instance.name, provider_instance)
                        except Exception as e:
                            print(f"Failed to instantiate {name}: {e}")

                            
    def _register_provider(self, name: str, provider: LLMProvider):
        self.providers[name.lower()] = provider

    def _get_provider(self, name: str) -> LLMProvider:
        """Helper to fetch the provider instance by its string name."""
        provider = self.providers.get(name.lower())
        if not provider:
            raise ValueError(f"Unknown provider configured: {name}")
        return provider

    def get_route(self, task: TaskType) -> LLMRoute:
        return self._routes[task]

    async def call_structured(
        self,
        *,
        system_prompt: str,
        response_model: Type[T],
        schema_name: str,
        schema_description: str,
        temperature: float = 0.0,
        max_tokens: int = 800,
        chat_history: Sequence[Message] | None = None,
        task_type: TaskType = TaskType.STRUCTURED,
        model: LLMRoute | None = None,
        file_media_mode: FileMediaMode = FileMediaMode.MEDIA,
    ) -> T | None:
        
        if model is None:
            model = self.get_route(task_type)

        return await model.provider.call_structured(
            system_prompt=system_prompt,
            response_model=response_model,
            schema_name=schema_name,
            schema_description=schema_description,
            temperature=temperature,
            max_tokens=max_tokens,
            chat_history=chat_history,
            model_id=model.model_id,
            file_media_mode=file_media_mode,
        )

    async def call_stream(
        self,
        *,
        system_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
        chat_history: Sequence[Message] | None = None,
        task_type: TaskType = TaskType.REASONING,
        model: LLMRoute | None = None,
        file_media_mode: FileMediaMode = FileMediaMode.MEDIA,
    ) -> AsyncIterator[str]:
        
        if model is None:
            model = self.get_route(task_type)

        async for chunk in model.provider.call_stream(
            temperature=temperature,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            chat_history=chat_history,
            model_id=model.model_id,
            file_media_mode=file_media_mode,
        ):
            yield chunk

    async def call_converse(
        self,
        *,
        system_prompt: str,
        chat_history: Sequence[Message] | None = None,
        tools: list[ToolDescriptor] | None = None,
        tool_call_records: Sequence[AgentToolCallRecord] = (),
        temperature: float = 0.1,
        max_tokens: int = 4096,
        task_type: TaskType = TaskType.REASONING,
        model: LLMRoute | None = None,
        file_media_mode: FileMediaMode = FileMediaMode.MEDIA,
    ) -> ConverseResponse:
        if model is None:
            model = self.get_route(task_type)

        return await model.provider.call_converse(
            system_prompt=system_prompt,
            tools=tools,
            tool_call_records=tool_call_records,
            temperature=temperature,
            max_tokens=max_tokens,
            chat_history=chat_history,
            model_id=model.model_id,
            file_media_mode=file_media_mode,
        )

    async def call_standard_with_document(
        self,
        *,
        system_prompt: str,
        document_bytes: bytes,
        document_name: str,
        document_format: str,
        chat_history: Sequence[Message] | None = None,
        task_type: TaskType = TaskType.DOCUMENT,
        model: LLMRoute | None = None,
    ) -> dict[str, Any]:
        
        if model is None:
            model = self.get_route(task_type)

        return await model.provider.call_standard_with_document(
            system_prompt=system_prompt,
            document_bytes=document_bytes,
            document_name=document_name,
            document_format=document_format,
            chat_history=chat_history,
            model_id=model.model_id,
        )
