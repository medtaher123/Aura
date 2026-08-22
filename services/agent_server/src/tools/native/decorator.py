"""Mark in-process functions as native tools for auto-discovery."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

NATIVE_TOOL_ATTR = "__native_tool__"
NATIVE_TOOL_NAME_ATTR = "__native_tool_name__"


def native_tool(fn: F | None = None, *, name: str | None = None) -> F | Callable[[F], F]:
    """Decorator that registers a function as a discoverable native tool.

    Usage::

        @native_tool
        def get_time() -> ToolResponse: ...

        @native_tool(name="calc")
        def calculator(expression: str) -> ToolResponse: ...
    """

    def decorate(func: F) -> F:
        setattr(func, NATIVE_TOOL_ATTR, True)
        setattr(func, NATIVE_TOOL_NAME_ATTR, name or func.__name__)
        return func

    if fn is not None:
        return decorate(fn)
    return decorate


def is_native_tool(obj: Any) -> bool:
    return callable(obj) and bool(getattr(obj, NATIVE_TOOL_ATTR, False))


def native_tool_name(obj: Any) -> str | None:
    if not is_native_tool(obj):
        return None
    return str(getattr(obj, NATIVE_TOOL_NAME_ATTR, None) or getattr(obj, "__name__", ""))
