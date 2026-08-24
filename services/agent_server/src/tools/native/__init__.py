"""In-process native tools (auto-discovered via ``NativeTool`` / ``@native_tool``).

Subclass ``NativeTool`` or decorate a function with ``@native_tool`` under
this package; ``build_default_native_provider`` picks them up on startup.
"""

from src.tools.native.base import NativeTool
from src.tools.native.decorator import native_tool

__all__ = ["NativeTool", "native_tool"]
