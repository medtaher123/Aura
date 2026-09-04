"""Bedrock file media cache, Converse blocks, and caption vs media mode."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from eo_llm.adapters.bedrock.llm_providers.bedrock_helpers.file_media import (
    BedrockDocumentName,
    BedrockFileFormat,
    BedrockFileMedia,
    BedrockFileMediaCache,
    BedrockMediaKind,
    BedrockMediaSource,
    BedrockS3LocationPolicy,
    build_bedrock_file_media,
)
from eo_llm.adapters.bedrock.llm_providers.bedrock_helpers.file_media_context import (
    reset_file_catalog,
    set_file_catalog,
)
from eo_llm.adapters.bedrock.llm_provider import FileMediaMode
from eo_llm.adapters.bedrock.llm_providers.bedrockProvider import BedrockProvider
from eo_llm.document_store import MAX_DOCUMENT_BYTES
from src.config import get_config
from src.db.base import BaseModel
from src.db.models.file import File
from src.db.models.message import UserMessage
from src.db.models.message_attachments import FileAttachment
from src.db.models.user import User
from src.db.services.files import FileService
from src.files.catalog import FileCatalog
from src.files.router import FileStorageRouter


def _pdf_media(file_id, *, name="brief", s3_uri=None, payload=b"%PDF"):
    source = (
        BedrockMediaSource(s3_uri=s3_uri)
        if s3_uri
        else BedrockMediaSource(payload_bytes=payload)
    )
    return BedrockFileMedia(
        file_id=file_id,
        kind=BedrockMediaKind.DOCUMENT,
        format="pdf",
        name=name,
        source=source,
    )


def _image_media(file_id, *, payload=b"\x89PNG"):
    return BedrockFileMedia(
        file_id=file_id,
        kind=BedrockMediaKind.IMAGE,
        format="png",
        name="map",
        source=BedrockMediaSource(payload_bytes=payload),
    )


def _format_with_cache(messages, cache: BedrockFileMediaCache, mode: FileMediaMode):
    token = set_file_catalog(cache._catalog, media_cache=cache)
    try:
        return BedrockProvider().format_messages(messages, file_media_mode=mode)
    finally:
        reset_file_catalog(token)


def test_bedrock_document_name_strips_unsafe_characters():
    assert BedrockDocumentName.from_filename("Q3 report (final)!.pdf") == "Q3 report (final)"
    assert BedrockDocumentName.from_filename("!!!") == "document"


def test_bedrock_file_format_from_content_type_and_extension():
    pdf = BedrockFileFormat.from_filename_and_type("x.bin", "application/pdf")
    assert pdf is not None
    assert pdf.kind is BedrockMediaKind.DOCUMENT
    assert pdf.format == "pdf"

    png = BedrockFileFormat.from_filename_and_type("map.PNG", "application/octet-stream")
    assert png is not None
    assert png.kind is BedrockMediaKind.IMAGE
    assert png.format == "png"

    assert BedrockFileFormat.from_filename_and_type("notes.zip", "application/zip") is None


def test_s3_location_policy_requires_aws_s3(monkeypatch):
    record = File(
        id=uuid4(),
        user_id="owner",
        original_filename="brief.pdf",
        content_type="application/pdf",
        size_bytes=10,
        checksum_sha256="a" * 64,
        storage_provider="s3",
        storage_key="owner/id/brief.pdf",
    )
    monkeypatch.setenv("FILE_STORAGE_S3_BUCKET", "metaplanet-files")
    monkeypatch.delenv("FILE_STORAGE_S3_ENDPOINT_URL", raising=False)
    get_config.cache_clear()
    assert BedrockS3LocationPolicy.applies_to(record)
    assert BedrockS3LocationPolicy.uri_for(record) == "s3://metaplanet-files/owner/id/brief.pdf"

    monkeypatch.setenv("FILE_STORAGE_S3_ENDPOINT_URL", "http://localhost:9000")
    get_config.cache_clear()
    assert not BedrockS3LocationPolicy.applies_to(record)

    record.storage_provider = "local"
    monkeypatch.delenv("FILE_STORAGE_S3_ENDPOINT_URL", raising=False)
    get_config.cache_clear()
    assert not BedrockS3LocationPolicy.applies_to(record)
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_build_media_uses_s3_location_without_reading_bytes(monkeypatch):
    record = File(
        id=uuid4(),
        user_id="owner",
        original_filename="brief.pdf",
        content_type="application/pdf",
        size_bytes=10,
        checksum_sha256="a" * 64,
        storage_provider="s3",
        storage_key="owner/id/brief.pdf",
    )
    monkeypatch.setenv("FILE_STORAGE_S3_BUCKET", "metaplanet-files")
    monkeypatch.delenv("FILE_STORAGE_S3_ENDPOINT_URL", raising=False)
    get_config.cache_clear()
    catalog = FileCatalog("owner")
    catalog._records[record.id] = record
    monkeypatch.setattr(
        FileStorageRouter,
        "get_provider",
        lambda: (_ for _ in ()).throw(AssertionError("must not read bytes")),
    )
    media = await build_bedrock_file_media(catalog, record.id)
    assert media is not None
    assert media.to_content_block()["document"]["source"] == {
        "s3Location": {"uri": "s3://metaplanet-files/owner/id/brief.pdf"}
    }
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_build_media_inlines_bytes_for_local_and_minio(monkeypatch):
    record = File(
        id=uuid4(),
        user_id="owner",
        original_filename="brief.pdf",
        content_type="application/pdf",
        size_bytes=8,
        checksum_sha256="a" * 64,
        storage_provider="s3",
        storage_key="owner/id/brief.pdf",
    )
    fake = AsyncMock()
    fake.get = AsyncMock(return_value=b"%PDF-min")
    monkeypatch.setenv("FILE_STORAGE_S3_BUCKET", "minio-bucket")
    monkeypatch.setenv("FILE_STORAGE_S3_ENDPOINT_URL", "http://localhost:9000")
    get_config.cache_clear()
    catalog = FileCatalog("owner")
    catalog._records[record.id] = record
    monkeypatch.setattr(FileStorageRouter, "get_provider", lambda: fake)
    media = await build_bedrock_file_media(catalog, record.id)
    assert media is not None
    assert media.to_content_block()["document"]["source"] == {"bytes": b"%PDF-min"}
    fake.get.assert_awaited_once_with("owner/id/brief.pdf")
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_build_media_skips_oversized_files():
    record = File(
        id=uuid4(),
        user_id="owner",
        original_filename="huge.pdf",
        content_type="application/pdf",
        size_bytes=MAX_DOCUMENT_BYTES + 1,
        checksum_sha256="a" * 64,
        storage_provider="local",
        storage_key="owner/id/huge.pdf",
    )
    catalog = FileCatalog("owner")
    catalog._records[record.id] = record
    assert await build_bedrock_file_media(catalog, record.id) is None


@pytest.mark.asyncio
async def test_cache_loads_each_file_id_once(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_PROVIDER", "local")
    monkeypatch.setenv("FILE_STORAGE_LOCAL_ROOT", str(tmp_path))
    get_config.cache_clear()
    FileStorageRouter.initialize()

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        user = User(id="owner", provider="test", email="o@t.com", username="owner")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        stored = await FileService(db).save(
            user,
            filename="report.pdf",
            content_type="application/pdf",
            data=b"%PDF-once",
        )
        attachment = FileAttachment(file_id=stored.id, name="report.pdf")
        messages = [
            UserMessage.create("first", attachments=[attachment]),
            UserMessage.create("again", attachments=[attachment]),
        ]
        catalog = FileCatalog(user.id, db=db)
        cache = BedrockFileMediaCache(catalog)
        original_get = FileStorageRouter.get_provider().get
        calls: list[str] = []

        async def _counting_get(key: str) -> bytes:
            calls.append(key)
            return await original_get(key)

        monkeypatch.setattr(FileStorageRouter.get_provider(), "get", _counting_get)
        await cache.load_for_messages(messages)
        assert len(cache) == 1
        assert cache.get(stored.id) is not None
        assert calls == [stored.storage_key]
    await engine.dispose()
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_cache_is_empty_until_loaded():
    catalog = FileCatalog("owner")
    cache = BedrockFileMediaCache(catalog)
    file_id = uuid4()
    assert cache.get(file_id) is None
    assert len(cache) == 0


def test_bedrock_formats_document_and_image_blocks():
    pdf_id = uuid4()
    png_id = uuid4()
    catalog = FileCatalog("owner")
    cache = BedrockFileMediaCache(catalog)
    cache._items = {
        pdf_id: _pdf_media(pdf_id, s3_uri="s3://bucket/a.pdf"),
        png_id: _image_media(png_id),
    }
    message = UserMessage.create(
        "Look at these",
        attachments=[
            FileAttachment(file_id=pdf_id, name="a.pdf"),
            FileAttachment(file_id=png_id, name="map.png"),
        ],
    )
    formatted = _format_with_cache([message], cache, FileMediaMode.MEDIA)
    blocks = formatted[0]["content"]
    assert blocks[0] == {"text": "Look at these"}
    assert blocks[1]["document"]["format"] == "pdf"
    assert blocks[1]["document"]["source"]["s3Location"]["uri"] == "s3://bucket/a.pdf"
    assert blocks[2]["image"]["format"] == "png"
    assert blocks[2]["image"]["source"]["bytes"] == b"\x89PNG"
    assert blocks[-1] == {"cachePoint": {"type": "default"}}


def test_structured_mode_keeps_captions_without_media_bytes():
    file_id = uuid4()
    catalog = FileCatalog("owner")
    cache = BedrockFileMediaCache(catalog)
    cache._items = {file_id: _pdf_media(file_id, payload=b"%PDF-secret")}
    message = UserMessage.create(
        "Summarize",
        attachments=[FileAttachment(file_id=file_id, name="secret.pdf")],
    )
    formatted = _format_with_cache([message], cache, FileMediaMode.CAPTION)
    blocks = formatted[0]["content"]
    assert all("document" not in block and "image" not in block for block in blocks)
    assert "s3Location" not in repr(blocks)
    assert "%PDF-secret" not in repr(blocks)
    assert any("secret.pdf" in block.get("text", "") for block in blocks)
    assert not any("cachePoint" in block for block in blocks)


def test_media_mode_adds_placeholder_text_when_message_is_file_only():
    file_id = uuid4()
    catalog = FileCatalog("owner")
    cache = BedrockFileMediaCache(catalog)
    cache._items = {file_id: _pdf_media(file_id)}
    message = UserMessage.create(
        "",
        attachments=[FileAttachment(file_id=file_id, name="brief.pdf")],
    )
    formatted = _format_with_cache([message], cache, FileMediaMode.MEDIA)
    blocks = formatted[0]["content"]
    assert blocks[0] == {"text": " "}
    assert "document" in blocks[1]
    assert blocks[-1] == {"cachePoint": {"type": "default"}}


def test_media_mode_caps_documents_per_message():
    ids = [uuid4() for _ in range(6)]
    catalog = FileCatalog("owner")
    cache = BedrockFileMediaCache(catalog)
    cache._items = {
        file_id: _pdf_media(file_id, name=f"doc{i}") for i, file_id in enumerate(ids)
    }
    message = UserMessage.create(
        "Many files",
        attachments=[
            FileAttachment(file_id=file_id, name=f"doc{i}.pdf")
            for i, file_id in enumerate(ids)
        ],
    )
    formatted = _format_with_cache([message], cache, FileMediaMode.MEDIA)
    blocks = formatted[0]["content"]
    documents = [block for block in blocks if "document" in block]
    captions = [
        block
        for block in blocks
        if block.get("text", "").startswith("Attached file:")
    ]
    assert len(documents) == 5
    assert len(captions) == 1
    assert captions[0]["text"] == "Attached file: doc5.pdf."
    assert blocks[-1] == {"cachePoint": {"type": "default"}}


@pytest.mark.asyncio
async def test_router_uses_caption_for_structured_and_media_for_stream():
    from pydantic import BaseModel

    from eo_llm.adapters.bedrock.llm_provider import FileMediaMode
    from eo_llm.adapters.bedrock.llm_model_router import LLMModelRouter, LLMRoute
    from eo_llm.adapters.bedrock.llm_provider import ConverseResponse, LLMProvider

    class _Schema(BaseModel):
        ok: bool = True

    seen: dict[str, FileMediaMode] = {}

    class _Spy(LLMProvider):
        @property
        def name(self) -> str:
            return "spy"

        @property
        def last_failure_reason(self) -> str:
            return ""

        async def call_structured(self, **kwargs):
            seen["structured"] = kwargs.get(
                "file_media_mode", FileMediaMode.CAPTION
            )
            return None

        async def call_stream(self, **kwargs):
            seen["stream"] = kwargs.get("file_media_mode", FileMediaMode.CAPTION)
            if False:
                yield ""

        async def call_converse(self, **kwargs):
            return ConverseResponse(stop_reason="end_turn", text="ok")

        async def call_converse_stream(self, **kwargs):
            return ConverseResponse(stop_reason="end_turn", text="ok")

        async def call_standard_with_document(self, **kwargs):
            return {}

    route = LLMRoute(provider=_Spy(), model_id="model")
    router = LLMModelRouter()
    await router.call_structured(
        system_prompt="s",
        response_model=_Schema,
        schema_name="schema",
        schema_description="d",
        model=route,
    )
    async for _ in router.call_stream(system_prompt="s", model=route):
        pass
    assert seen["structured"] is FileMediaMode.CAPTION
    assert seen["stream"] is FileMediaMode.MEDIA
