"""Bedrock Converse document/image blocks for stored chat files."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eo_llm.document_store import MAX_DOCUMENT_BYTES
from src.config import get_config
from src.db.models.file import File
from src.files.catalog import FileCatalog

if TYPE_CHECKING:
    from src.db.models.message import Message

logger = logging.getLogger("eo_llm.bedrock.file_media")

MAX_DOCUMENTS_PER_MESSAGE = 5

_DOCUMENT_FORMATS = {
    "pdf": "pdf",
    "csv": "csv",
    "doc": "doc",
    "docx": "docx",
    "xls": "xls",
    "xlsx": "xlsx",
    "html": "html",
    "htm": "html",
    "txt": "txt",
    "md": "md",
    "markdown": "md",
}
_IMAGE_FORMATS = {
    "png": "png",
    "jpeg": "jpeg",
    "jpg": "jpeg",
    "gif": "gif",
    "webp": "webp",
}
_CONTENT_TYPE_FORMATS = {
    "application/pdf": ("document", "pdf"),
    "text/csv": ("document", "csv"),
    "text/plain": ("document", "txt"),
    "text/html": ("document", "html"),
    "text/markdown": ("document", "md"),
    "application/msword": ("document", "doc"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "document",
        "docx",
    ),
    "application/vnd.ms-excel": ("document", "xls"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "document",
        "xlsx",
    ),
    "image/png": ("image", "png"),
    "image/jpeg": ("image", "jpeg"),
    "image/gif": ("image", "gif"),
    "image/webp": ("image", "webp"),
}


class BedrockMediaKind(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"


class BedrockDocumentName:
    """Sanitize a filename into a Bedrock Converse document ``name``."""

    _UNSAFE = re.compile(r"[^A-Za-z0-9 \-\(\)\[\]]+")
    _SPACES = re.compile(r"\s+")

    @classmethod
    def from_filename(cls, filename: str) -> str:
        stem = Path(filename or "").stem
        cleaned = cls._SPACES.sub(" ", cls._UNSAFE.sub(" ", stem)).strip()
        return (cleaned or "document")[:200]


class BedrockFileFormat(BaseModel):
    kind: BedrockMediaKind
    format: str

    @classmethod
    def from_filename_and_type(
        cls,
        filename: str,
        content_type: str,
    ) -> Optional[BedrockFileFormat]:
        mime = (content_type or "").split(";", 1)[0].strip().lower()
        mapped = _CONTENT_TYPE_FORMATS.get(mime)
        if mapped is not None:
            kind, fmt = mapped
            return cls(kind=BedrockMediaKind(kind), format=fmt)
        ext = Path(filename or "").suffix.lstrip(".").lower()
        if ext in _DOCUMENT_FORMATS:
            return cls(kind=BedrockMediaKind.DOCUMENT, format=_DOCUMENT_FORMATS[ext])
        if ext in _IMAGE_FORMATS:
            return cls(kind=BedrockMediaKind.IMAGE, format=_IMAGE_FORMATS[ext])
        return None


class BedrockS3LocationPolicy:
    """Bedrock can fetch AWS S3 objects; it cannot fetch MinIO or local disk."""

    @staticmethod
    def applies_to(record: File) -> bool:
        if record.storage_provider != "s3":
            return False
        config = get_config()
        if (config.file_storage_s3_endpoint_url or "").strip():
            return False
        return bool((config.file_storage_s3_bucket or "").strip())

    @staticmethod
    def uri_for(record: File) -> str:
        bucket = (get_config().file_storage_s3_bucket or "").strip()
        key = record.storage_key.lstrip("/")
        return f"s3://{bucket}/{key}"


class BedrockMediaSource(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    payload_bytes: bytes | None = None
    s3_uri: str | None = None

    def to_converse_source(self) -> dict[str, Any]:
        if self.s3_uri:
            return {"s3Location": {"uri": self.s3_uri}}
        if self.payload_bytes is not None:
            return {"bytes": self.payload_bytes}
        raise ValueError("Bedrock media source is empty")


class BedrockFileMedia(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    file_id: UUID
    kind: BedrockMediaKind
    format: str
    name: str
    source: BedrockMediaSource

    def to_content_block(self) -> dict[str, Any]:
        source = self.source.to_converse_source()
        if self.kind is BedrockMediaKind.IMAGE:
            return {"image": {"format": self.format, "source": source}}
        return {
            "document": {
                "format": self.format,
                "name": self.name,
                "source": source,
            }
        }


async def build_bedrock_file_media(
    catalog: FileCatalog,
    file_id: UUID,
) -> BedrockFileMedia | None:
    record = await catalog.get_record(file_id)
    if record is None:
        return None
    classified = BedrockFileFormat.from_filename_and_type(
        record.original_filename,
        record.content_type,
    )
    if classified is None:
        return None
    if record.size_bytes > MAX_DOCUMENT_BYTES:
        logger.info(
            "Skipping Bedrock media for file %s: %s bytes exceeds cap",
            record.id,
            record.size_bytes,
        )
        return None
    source = await _source_for_record(catalog, record)
    if source is None:
        return None
    return BedrockFileMedia(
        file_id=record.id,
        kind=classified.kind,
        format=classified.format,
        name=BedrockDocumentName.from_filename(record.original_filename),
        source=source,
    )


async def _source_for_record(
    catalog: FileCatalog,
    record: File,
) -> BedrockMediaSource | None:
    if BedrockS3LocationPolicy.applies_to(record):
        return BedrockMediaSource(s3_uri=BedrockS3LocationPolicy.uri_for(record))
    payload = await catalog.read_bytes(record.id)
    if not payload or len(payload) > MAX_DOCUMENT_BYTES:
        return None
    return BedrockMediaSource(payload_bytes=payload)


class BedrockFileMediaCache:
    """Lazy Bedrock media blocks backed by a generic ``FileCatalog``."""

    def __init__(self, catalog: FileCatalog) -> None:
        self._catalog = catalog
        self._items: dict[UUID, BedrockFileMedia | None] = {}

    def get(self, file_id: UUID) -> BedrockFileMedia | None:
        if file_id not in self._items:
            return None
        return self._items[file_id]

    def __len__(self) -> int:
        return sum(1 for value in self._items.values() if value is not None)

    async def load_for_messages(self, messages: Sequence["Message"]) -> None:
        for file_id in FileCatalog.file_ids_from_messages(messages):
            await self._load_one(file_id)

    async def _load_one(self, file_id: UUID) -> None:
        if file_id in self._items:
            return
        self._items[file_id] = await build_bedrock_file_media(self._catalog, file_id)
