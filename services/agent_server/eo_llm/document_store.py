"""Local document storage for uploaded files used by graph runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_DOCUMENT_BYTES = 4_500_000


def load_document_bytes(document_ref: dict[str, Any]) -> bytes:
    """Load bytes for a previously saved document reference."""
    path_value = str(document_ref.get("path") or "").strip()
    if not path_value:
        raise ValueError("Document reference has no file path.")
    path = Path(path_value)
    if not path.exists():
        raise ValueError("Uploaded document was not found on disk.")
    data = path.read_bytes()
    if not data:
        raise ValueError("Uploaded document is empty.")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("Uploaded document exceeds supported size.")
    return data
