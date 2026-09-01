"""Tests for Streamlit file attach helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "ui" / "file_input.py"
_SPEC = importlib.util.spec_from_file_location("file_input", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_file_input = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_file_input)
file_attachment = _file_input.file_attachment
upload_file_to_agent = _file_input.upload_file_to_agent
FileUploadError = _file_input.FileUploadError
MAX_FILE_BYTES = _file_input.MAX_FILE_BYTES


def test_file_attachment_shape():
    payload = file_attachment("abc-123", "report.pdf")
    assert payload == {
        "type": "file",
        "file_id": "abc-123",
        "name": "report.pdf",
    }


def test_upload_file_to_agent_posts_multipart():
    response = MagicMock()
    response.status_code = 201
    response.json.return_value = {
        "id": "11111111-1111-1111-1111-111111111111",
        "original_filename": "notes.txt",
    }
    with patch.object(_file_input.requests, "post", return_value=response) as post:
        stored = upload_file_to_agent(
            "http://localhost:8080",
            "tok",
            filename="notes.txt",
            data=b"hello",
            content_type="text/plain",
            conversation_id="cid-1",
        )
    assert stored["id"] == "11111111-1111-1111-1111-111111111111"
    kwargs = post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["files"]["file"][0] == "notes.txt"
    assert kwargs["files"]["file"][1] == b"hello"
    assert kwargs["data"]["conversation_id"] == "cid-1"


def test_upload_file_to_agent_rejects_empty_and_unauthenticated():
    with pytest.raises(FileUploadError, match="empty"):
        upload_file_to_agent("http://localhost:8080", "tok", filename="a.txt", data=b"")
    with pytest.raises(FileUploadError, match="Sign in"):
        upload_file_to_agent(
            "http://localhost:8080", None, filename="a.txt", data=b"hello"
        )
    with pytest.raises(FileUploadError, match="too large"):
        upload_file_to_agent(
            "http://localhost:8080",
            "tok",
            filename="a.bin",
            data=b"x" * (MAX_FILE_BYTES + 1),
        )
