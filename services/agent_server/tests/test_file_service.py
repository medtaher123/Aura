"""Tests for FileService orchestration against sqlite + local storage."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config import get_config
from src.db.base import BaseModel
from src.db.models.user import User
from src.db.services.files import EmptyFileError, FileService, FileTooLargeError
from src.files.router import FileStorageRouter


async def _session(tmp_path, monkeypatch):
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
    return engine, factory


@pytest.mark.asyncio
async def test_file_service_save_get_delete(tmp_path, monkeypatch):
    engine, factory = await _session(tmp_path, monkeypatch)
    async with factory() as db:
        user = User(id="owner", provider="test", email="o@t.com", username="owner")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        service = FileService(db)
        stored = await service.save(
            user,
            filename="report.pdf",
            content_type="application/pdf",
            data=b"%PDF-test",
        )
        assert stored.original_filename == "report.pdf"
        assert stored.size_bytes == len(b"%PDF-test")
        assert stored.storage_provider == "local"
        assert stored.checksum_sha256
        assert user.id in stored.storage_key

        loaded = await service.get_for_user(user, stored.id)
        assert loaded is not None
        assert await service.read_bytes(user, stored.id) == b"%PDF-test"

        other = User(id="other", provider="test", email="x@t.com", username="other")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        assert await service.get_for_user(other, stored.id) is None

        assert await service.delete(user, stored.id) is True
        assert await service.get_for_user(user, stored.id) is None
        assert not (tmp_path / stored.storage_key).exists()
    await engine.dispose()
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_file_service_rejects_empty_and_oversized(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_MAX_BYTES", "8")
    engine, factory = await _session(tmp_path, monkeypatch)
    async with factory() as db:
        user = User(id="owner", provider="test", email="o@t.com", username="owner")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        service = FileService(db)
        with pytest.raises(EmptyFileError):
            await service.save(
                user, filename="a.txt", content_type="text/plain", data=b""
            )
        with pytest.raises(FileTooLargeError):
            await service.save(
                user, filename="a.txt", content_type="text/plain", data=b"0123456789"
            )
        assert await service.delete(user, uuid4()) is False
    await engine.dispose()
    get_config.cache_clear()
