"""Stored-file HTTP endpoints.

Uploads are scoped to the authenticated user. Bytes go to FileStorageProvider;
metadata is persisted in the ``files`` table.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import User, get_db
from src.db.services import EmptyFileError, FileService, FileTooLargeError
from src.schemas.files import FileRead

from .deps import get_current_user

router = APIRouter(prefix="/files", tags=["files"])


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: uuid.UUID | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileRead:
    """Store an uploaded file for the authenticated user."""
    data = await file.read()
    try:
        stored = await FileService(db).save(
            user,
            filename=file.filename or "file",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            conversation_id=conversation_id,
        )
    except EmptyFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return FileRead.from_model(stored)


@router.get("/{file_id}", response_model=FileRead)
async def get_file_metadata(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileRead:
    """Return metadata for a file owned by the caller."""
    stored = await FileService(db).get_for_user(user, file_id)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
    return FileRead.from_model(stored)


@router.get("/{file_id}/content")
async def download_file(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download file bytes owned by the caller."""
    service = FileService(db)
    stored = await service.get_for_user(user, file_id)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
    data = await service.read_bytes(user, file_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
    filename = quote(stored.original_filename)
    return Response(
        content=data,
        media_type=stored.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a file owned by the caller from storage and the database."""
    deleted = await FileService(db).delete(user, file_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
