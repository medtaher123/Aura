"""In-process native tools (auto-discovered via ``@native_tool``).

Add a module under this package, decorate callables with ``@native_tool``,
and ``build_default_native_provider`` will pick them up automatically.
"""

from src.tools.native.decorator import native_tool

__all__ = ["native_tool"]
