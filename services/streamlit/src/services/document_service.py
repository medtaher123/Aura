from __future__ import annotations

import io
from core.logger import get_logger

logger = get_logger(__name__)


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
        logger.error("Empty PDF payload provided")
        raise ValueError("Empty PDF payload")

    logger.info(
        f"Starting PDF text extraction (size: {len(pdf_bytes)} bytes, max_chars: {max_chars})"
    )

    try:
        from pypdf import PdfReader
    except Exception as e:  # pragma: no cover
        logger.error(f"pypdf dependency missing: {e}")
        raise RuntimeError("Missing dependency: install pypdf") from e

    try:
        reader = PdfReader(io.BytesIO(bytes(pdf_bytes)))
        logger.debug(f"PDF loaded successfully, pages: {len(reader.pages)}")
    except Exception as e:
        logger.error(f"Failed to read PDF: {type(e).__name__}: {str(e)}")
        raise

    parts: list[str] = []
    total = 0

    for page_num, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
            text = text.replace("\x00", "").strip()
            if not text:
                logger.debug(f"Page {page_num}: No text extracted")
                continue

            remaining = max_chars - total
            if remaining <= 0:
                logger.info(f"Reached max_chars limit at page {page_num}")
                break

            if len(text) > remaining:
                logger.debug(
                    f"Page {page_num}: Truncating text from {len(text)} to {remaining} chars"
                )
                text = text[:remaining]

            parts.append(text)
            total += len(text)
            logger.debug(
                f"Page {page_num}: Extracted {len(text)} chars (total: {total})"
            )

            if total >= max_chars:
                break
        except Exception as e:
            logger.warning(
                f"Error extracting text from page {page_num}: {type(e).__name__}: {str(e)}"
            )
            continue

    result = "\n\n".join(parts).strip()
    logger.info(f"PDF extraction complete: {total} chars from {len(parts)} pages")
    return result
