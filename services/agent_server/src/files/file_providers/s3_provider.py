"""S3-compatible object storage (AWS S3 and MinIO)."""

from __future__ import annotations

from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from src.config import get_config

from ..provider import (
    FileStorageConfigurationError,
    FileStorageError,
    FileStorageProvider,
)


class S3FileStorageProvider(FileStorageProvider):
    """Store file bytes in an S3-compatible bucket.

    Set ``file_storage_s3_endpoint_url`` for MinIO; omit it for AWS S3.
    Access keys are optional — AWS typically uses the task-role credential chain.
    """

    name = "s3"

    def __init__(self) -> None:
        config = get_config()
        bucket = (config.file_storage_s3_bucket or "").strip()
        if not bucket:
            raise FileStorageConfigurationError(
                "FILE_STORAGE_S3_BUCKET is required when file_storage_provider=s3"
            )
        self._bucket = bucket
        self._prefix = (config.file_storage_s3_prefix or "").strip("/")
        self._endpoint_url = (config.file_storage_s3_endpoint_url or "").strip() or None
        self._access_key = (config.file_storage_s3_access_key or "").strip() or None
        self._secret_key = (config.file_storage_s3_secret_key or "").strip() or None
        region = (
            config.file_storage_s3_region or config.bedrock_region or "eu-west-3"
        )
        self._session = aioboto3.Session(region_name=region)

    def build_key(self, *parts: str) -> str:
        chunks = [part.strip("/") for part in parts if part and part.strip("/")]
        if self._prefix:
            chunks = [self._prefix, *chunks]
        return "/".join(chunks)

    def _client(self) -> Any:
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        if self._access_key:
            kwargs["aws_access_key_id"] = self._access_key
            kwargs["aws_secret_access_key"] = self._secret_key or ""
        return self._session.client("s3", **kwargs)

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        try:
            async with self._client() as s3:
                await s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=data,
                    **extra,
                )
        except ClientError as exc:
            raise FileStorageError("Failed to store file in object storage") from exc

    async def get(self, key: str) -> bytes:
        try:
            async with self._client() as s3:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
                body = response["Body"]
                return await body.read()
        except ClientError as exc:
            raise FileStorageError("Stored file was not found in object storage") from exc

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as s3:
                await s3.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise FileStorageError("Failed to delete file from object storage") from exc

    async def exists(self, key: str) -> bool:
        try:
            async with self._client() as s3:
                await s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise FileStorageError("Failed to stat file in object storage") from exc
