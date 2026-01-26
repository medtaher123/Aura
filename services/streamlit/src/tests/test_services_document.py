"""
Tests for services/document_service.py - PDF text extraction.
"""

import pytest
from io import BytesIO

from src.services.document_service import extract_text_from_pdf_bytes


class TestExtractTextFromPdfBytes:
    """Tests for extract_text_from_pdf_bytes function."""

    def test_empty_bytes_raises_value_error(self):
        with pytest.raises(ValueError, match="Empty PDF payload"):
            extract_text_from_pdf_bytes(b"")

    def test_none_raises_value_error(self):
        with pytest.raises(ValueError, match="Empty PDF payload"):
            extract_text_from_pdf_bytes(None)

    def test_non_bytes_raises_value_error(self):
        with pytest.raises(ValueError, match="Empty PDF payload"):
            extract_text_from_pdf_bytes("not bytes")

    def test_invalid_pdf_raises_error(self):
        # Random bytes that are not a valid PDF
        invalid_pdf = b"This is not a PDF file"
        with pytest.raises(Exception):
            extract_text_from_pdf_bytes(invalid_pdf)

    def test_valid_pdf_extracts_text(self):
        """Test with a minimal valid PDF."""
        # Create a simple PDF using pypdf
        try:
            from pypdf import PdfWriter
        except ImportError:
            pytest.skip("pypdf not installed")

        writer = PdfWriter()
        # Add a blank page
        writer.add_blank_page(width=72, height=72)
        
        buffer = BytesIO()
        writer.write(buffer)
        pdf_bytes = buffer.getvalue()

        result = extract_text_from_pdf_bytes(pdf_bytes)
        assert isinstance(result, str)

    def test_max_chars_truncation(self):
        """Test that text is truncated at max_chars."""
        try:
            from pypdf import PdfWriter
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
        except ImportError:
            pytest.skip("pypdf or reportlab not installed")

        # Create PDF with text using reportlab
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        # Write a long text
        long_text = "A" * 2000
        c.drawString(100, 700, long_text[:100])
        c.save()
        pdf_bytes = buffer.getvalue()

        result = extract_text_from_pdf_bytes(pdf_bytes, max_chars=50)
        assert len(result) <= 50

    def test_bytearray_accepted(self):
        """Test that bytearray is also accepted."""
        try:
            from pypdf import PdfWriter
        except ImportError:
            pytest.skip("pypdf not installed")

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        
        buffer = BytesIO()
        writer.write(buffer)
        pdf_bytes = bytearray(buffer.getvalue())

        result = extract_text_from_pdf_bytes(pdf_bytes)
        assert isinstance(result, str)

    def test_null_bytes_removed(self):
        """Test that null bytes are stripped from extracted text."""
        try:
            from pypdf import PdfWriter
        except ImportError:
            pytest.skip("pypdf not installed")

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        
        buffer = BytesIO()
        writer.write(buffer)
        pdf_bytes = buffer.getvalue()

        result = extract_text_from_pdf_bytes(pdf_bytes)
        assert "\x00" not in result
