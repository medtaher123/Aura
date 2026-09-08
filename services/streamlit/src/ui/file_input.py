"""Helpers for uploading a file and attaching it to a chat message."""

from __future__ import annotations

from typing import Any

import requests

MAX_FILE_BYTES = 10 * 1024 * 1024


class FileUploadError(Exception):
    """Raised when the agent-server file upload fails."""


def file_attachment(file_id: str, name: str = "") -> dict[str, Any]:
    """Build a ``type=file`` attachment for chat_request / chat_resume."""
    return {
        "type": "file",
        "file_id": str(file_id),
        "name": str(name or ""),
    }


def upload_file_to_agent(
    base_url: str,
    auth_token: str | None,
    *,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    conversation_id: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """POST bytes to ``/files`` and return the metadata JSON."""
    if not data:
        raise FileUploadError("Uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise FileUploadError(f"File too large (max {MAX_FILE_BYTES // (1024 * 1024)}MB)")

    headers: dict[str, str] = {}
    if auth_token:
        token = auth_token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if not headers.get("Authorization"):
        raise FileUploadError("Sign in to attach files")

    form: dict[str, str] = {}
    if conversation_id:
        form["conversation_id"] = str(conversation_id)

    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/files",
            headers=headers,
            files={
                "file": (
                    filename or "file",
                    data,
                    content_type or "application/octet-stream",
                )
            },
            data=form or None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise FileUploadError(f"Could not upload file: {exc}") from exc

    if response.status_code >= 400:
        detail = _error_detail(response)
        raise FileUploadError(detail)

    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("id"):
        raise FileUploadError("Upload response was missing a file id")
    return payload


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return text or f"Upload failed ({response.status_code})"
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
    return f"Upload failed ({response.status_code})"
