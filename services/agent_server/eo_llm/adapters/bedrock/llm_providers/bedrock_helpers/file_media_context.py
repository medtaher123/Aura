"""Request-scoped file catalog and Bedrock media cache."""

from __future__ import annotations

import contextvars
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from eo_llm.adapters.bedrock.llm_providers.bedrock_helpers.file_media import (
    BedrockFileMedia,
    BedrockFileMediaCache,
)
from src.files.catalog import FileCatalog

if TYPE_CHECKING:
    from src.db.models.message import Message

_file_catalog: contextvars.ContextVar[FileCatalog | None] = contextvars.ContextVar(
    "llm_file_catalog", default=None
)
_bedrock_media_cache: contextvars.ContextVar[BedrockFileMediaCache | None] = (
    contextvars.ContextVar("llm_bedrock_media_cache", default=None)
)


def set_file_catalog(
    catalog: FileCatalog | None,
    *,
    media_cache: BedrockFileMediaCache | None = None,
) -> contextvars.Token:
    token = _file_catalog.set(catalog)
    if catalog is None:
        _bedrock_media_cache.set(None)
    elif media_cache is not None:
        _bedrock_media_cache.set(media_cache)
    else:
        _bedrock_media_cache.set(BedrockFileMediaCache(catalog))
    return token


def reset_file_catalog(token: contextvars.Token) -> None:
    try:
        _file_catalog.reset(token)
    except (ValueError, LookupError):
        pass
    _bedrock_media_cache.set(None)


def get_bedrock_file_media(file_id: UUID) -> BedrockFileMedia | None:
    cache = _bedrock_media_cache.get()
    if cache is None:
        return None
    return cache.get(file_id)

#TODO: is this needed? MTBH
async def ensure_bedrock_media_for_messages(
    messages: Sequence["Message"],
) -> None:
    cache = _bedrock_media_cache.get()
    if cache is None or not messages:
        return
    await cache.load_for_messages(messages)
