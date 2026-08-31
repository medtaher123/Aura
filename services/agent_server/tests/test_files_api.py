"""HTTP tests for /files upload, download, and delete."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.api.deps import get_current_user
from src.config import get_config
from src.db.base import BaseModel
from src.db.database import get_db
from src.db.models.user import User
from src.files.router import FileStorageRouter
from src.main import app


@pytest_asyncio.fixture
async def files_client(tmp_path, monkeypatch):
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

    async with factory() as setup:
        setup.add(
            User(id="test_user", provider="test", email="t@t.com", username="tester")
        )
        await setup.commit()

    async def override_get_db():
        async with factory() as session:
            yield session

    async def override_get_current_user(
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user = await db.get(User, "test_user")
        assert user is not None
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_files_upload_download_delete(files_client):
    upload = await files_client.post(
        "/files",
        files={"file": ("hello.txt", b"hello world", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    file_id = body["id"]
    assert body["original_filename"] == "hello.txt"
    assert body["size_bytes"] == 11
    assert body["storage_provider"] == "local"
    assert "storage_key" not in body

    meta = await files_client.get(f"/files/{file_id}")
    assert meta.status_code == 200
    assert meta.json()["checksum_sha256"] == body["checksum_sha256"]

    download = await files_client.get(f"/files/{file_id}/content")
    assert download.status_code == 200
    assert download.content == b"hello world"
    assert "hello.txt" in download.headers.get("content-disposition", "")

    missing = await files_client.get(
        "/files/00000000-0000-0000-0000-000000000001"
    )
    assert missing.status_code == 404

    deleted = await files_client.delete(f"/files/{file_id}")
    assert deleted.status_code == 204
    gone = await files_client.get(f"/files/{file_id}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_files_reject_empty_upload(files_client):
    response = await files_client.post(
        "/files",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400
