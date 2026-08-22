"""Discover ``@native_tool`` callables under ``src.tools.native``."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable
from typing import Any

import src.tools.native as native_pkg
from src.tools.native.decorator import is_native_tool, native_tool_name

# Modules that are infrastructure, not tool definitions.
_SKIP_MODULES = frozenset(
    {
        "src.tools.native",
        "src.tools.native.decorator",
        "src.tools.native.discover",
    }
)


def discover_native_tools() -> list[tuple[str, Callable[..., Any], str]]:
    """Scan ``src.tools.native`` (and submodules) for ``@native_tool`` functions.

    Returns ``(name, handler, description)`` sorted by name. Duplicate names
    raise ``ValueError``.
    """
    found: dict[str, tuple[Callable[..., Any], str]] = {}

    for module in _iter_native_modules():
        for _, obj in inspect.getmembers(module, is_native_tool):
            name = native_tool_name(obj)
            if not name:
                continue
            description = inspect.getdoc(obj) or ""
            if name in found and found[name][0] is not obj:
                raise ValueError(
                    f"Duplicate native tool name {name!r} "
                    f"(in {module.__name__})"
                )
            found[name] = (obj, description)

    return [(name, handler, desc) for name, (handler, desc) in sorted(found.items())]


def _iter_native_modules():
    prefix = native_pkg.__name__ + "."
    for module_info in pkgutil.walk_packages(native_pkg.__path__, prefix):
        if module_info.name in _SKIP_MODULES:
            continue
        # Skip private helper modules (e.g. ``_internal``).
        short = module_info.name.rsplit(".", 1)[-1]
        if short.startswith("_"):
            continue
        yield importlib.import_module(module_info.name)
