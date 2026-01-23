from __future__ import annotations

import io


def extract_text_from_pdf_bytes(pdf_bytes: bytes, *, max_chars: int = 1000_000) -> str:
    """Extract plain text from a PDF byte payload.

    Args:
        pdf_bytes: Raw PDF bytes from upload.
        max_chars: Hard cap on extracted text length to avoid overly large prompts.

    Returns:
        Extracted text (may be truncated).

    Raises:
        RuntimeError: if PDF dependencies are missing.
        ValueError: if input is empty.
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)) or not pdf_bytes:
        raise ValueError("Empty PDF payload")

    try:
        from pypdf import PdfReader
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Missing dependency: install pypdf") from e

    reader = PdfReader(io.BytesIO(bytes(pdf_bytes)))

    parts: list[str] = []
    total = 0

    for page in reader.pages:
        text = page.extract_text() or ""
        text = text.replace("\x00", "").strip()
        if not text:
            continue

        remaining = max_chars - total
        if remaining <= 0:
            break

        if len(text) > remaining:
            text = text[:remaining]

        parts.append(text)
        total += len(text)

        if total >= max_chars:
            break

    return "\n\n".join(parts).strip()
