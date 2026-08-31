"""Tests for local and S3-compatible file storage providers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.files.file_providers.local_provider import LocalFileStorageProvider
from src.files.file_providers.s3_provider import S3FileStorageProvider
from src.files.provider import FileStorageError, InvalidStorageKeyError


@pytest.mark.asyncio
async def test_local_provider_put_get_delete(tmp_path):
    provider = LocalFileStorageProvider(root=tmp_path)
    key = provider.build_key("user-1", "file-1", "notes.txt")
    await provider.put(key, b"hello", content_type="text/plain")
    assert await provider.exists(key)
    assert await provider.get(key) == b"hello"
    await provider.delete(key)
    assert not await provider.exists(key)


@pytest.mark.asyncio
async def test_local_provider_rejects_path_traversal(tmp_path):
    provider = LocalFileStorageProvider(root=tmp_path)
    with pytest.raises(InvalidStorageKeyError):
        await provider.put("../secret.txt", b"no")
    with pytest.raises(InvalidStorageKeyError):
        await provider.get("/etc/passwd")
    with pytest.raises(InvalidStorageKeyError):
        await provider.put("", b"no")


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]

    async def get_object(self, **kwargs):
        key = kwargs["Key"]
        if key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        return {"Body": _FakeBody(self.objects[key])}

    async def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)

    async def head_object(self, **kwargs):
        if kwargs["Key"] not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )
        return {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_s3_provider_put_get_delete_with_prefix(monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_S3_BUCKET", "metaplanet-files")
    monkeypatch.setenv("FILE_STORAGE_S3_PREFIX", "uploads")
    from src.config import get_config

    get_config.cache_clear()
    provider = S3FileStorageProvider()
    fake = _FakeS3()
    provider._client = MagicMock(return_value=fake)

    key = provider.build_key("user-1", "file-1", "notes.txt")
    assert key == "uploads/user-1/file-1/notes.txt"
    await provider.put(key, b"payload", content_type="text/plain")
    assert await provider.exists(key)
    assert await provider.get(key) == b"payload"
    await provider.delete(key)
    assert not await provider.exists(key)
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_s3_provider_get_missing_raises(monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_S3_BUCKET", "metaplanet-files")
    from src.config import get_config

    get_config.cache_clear()
    provider = S3FileStorageProvider()
    provider._client = MagicMock(return_value=_FakeS3())
    with pytest.raises(FileStorageError):
        await provider.get("missing-key")
    get_config.cache_clear()
