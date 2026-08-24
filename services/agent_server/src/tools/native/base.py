"""Base class for in-process native tools."""

from __future__ import annotations

import inspect
import sys
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from src.tools.contracts import ToolResponse
from src.tools.native.decorator import native_tool

NATIVE_INPUT_SCHEMA_ATTR = "__native_input_schema__"


class NativeTool(ABC):
    """In-process tool registered via ``@native_tool`` on import.

    Subclasses set ``tool_name`` and implement ``invoke``. A handler is
    attached to the defining module for auto-discovery.
    """

    tool_name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "tool_name", None):
            return
        cls._register_handler()

    @classmethod
    def input_schema(cls) -> dict[str, Any] | None:
        """JSON Schema for tool arguments; ``None`` defers to the handler signature."""
        sig = inspect.signature(cls.invoke)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in sig.parameters.values():
            if param.name == "self":
                continue
            if param.kind not in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                continue
            properties[param.name] = {"type": "string"}
            if param.default is inspect.Parameter.empty:
                required.append(param.name)
        if not properties:
            return None
        return {"type": "object", "properties": properties, "required": required}

    @classmethod
    def _register_handler(cls) -> None:
        tool_name = cls.tool_name

        def handler(**kwargs: Any) -> ToolResponse:
            return cls().invoke(**kwargs)

        handler.__name__ = tool_name
        handler.__doc__ = inspect.cleandoc(cls.__doc__ or "")
        invoke_params = [
            p
            for p in inspect.signature(cls.invoke).parameters.values()
            if p.name != "self"
        ]
        handler.__signature__ = inspect.Signature(parameters=list(invoke_params))

        decorated = native_tool(name=tool_name)(handler)
        schema = cls.input_schema()
        if schema is not None:
            setattr(decorated, NATIVE_INPUT_SCHEMA_ATTR, schema)

        module = sys.modules.get(cls.__module__)
        if module is not None:
            setattr(module, tool_name, decorated)

    @abstractmethod
    def invoke(self, **kwargs: Any) -> ToolResponse:
        """Run the tool with keyword arguments from the gateway."""
