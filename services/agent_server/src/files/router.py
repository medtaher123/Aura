"""Selects the configured FileStorageProvider implementation."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

from src.config import get_config

from .provider import FileStorageConfigurationError, FileStorageProvider


class FileStorageRouter:
    """Discovers storage backends and keeps the one named in config."""

    _provider: FileStorageProvider | None = None
    _registry: dict[str, type[FileStorageProvider]] = {}

    @classmethod
    def initialize(cls) -> None:
        """Import provider modules and instantiate the configured backend."""
        cls._registry = {}
        cls._provider = None

        providers_dir = Path(__file__).resolve().parent / "file_providers"
        if providers_dir.exists() and providers_dir.is_dir():
            for _, module_name, _is_pkg in pkgutil.iter_modules([str(providers_dir)]):
                importlib.import_module(f"{__package__}.file_providers.{module_name}")

        for provider_class in FileStorageProvider.__subclasses__():
            if inspect.isabstract(provider_class):
                continue
            name = str(provider_class.name).lower()
            cls._registry[name] = provider_class

        wanted = get_config().file_storage_provider.strip().lower()
        provider_class = cls._registry.get(wanted)
        if provider_class is None:
            known = ", ".join(sorted(cls._registry)) or "(none)"
            raise FileStorageConfigurationError(
                f"Unknown file storage provider '{wanted}'. Known: {known}"
            )
        cls._provider = provider_class()

    @classmethod
    def get_provider(cls) -> FileStorageProvider:
        """Return the active storage backend, initializing on first use."""
        if cls._provider is None:
            cls.initialize()
        assert cls._provider is not None
        return cls._provider
