"""Shared runtime context passed to modules during init, health, and registration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config import MCPServerConfig
    from core.base import BaseModule
    from core.registry import ModuleRegistry


class SharedContext:
    """Process-wide resources and loaded module handles."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.modules: dict[str, BaseModule] = {}
        self.resources: dict[str, Any] = {}
        self.registry: ModuleRegistry | None = None
        self._engines: dict[str, Any] = {}

    def set_module(self, name: str, module: BaseModule) -> None:
        self.modules[name] = module

    def get_module(self, name: str) -> BaseModule | None:
        return self.modules.get(name)

    def set_resource(self, key: str, value: Any) -> None:
        self.resources[key] = value

    def get_resource(self, key: str, default: Any = None) -> Any:
        return self.resources.get(key, default)

    def get_engine(self, key: str) -> Any | None:
        return self._engines.get(key)

    def set_engine(self, key: str, engine: Any) -> None:
        self._engines[key] = engine
