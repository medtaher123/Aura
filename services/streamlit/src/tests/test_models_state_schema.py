"""
Tests for models/state_schema.py - Pydantic models for state management.
"""

import pytest
from pydantic import ValidationError

from models.state_schema import MyStateSchema


class TestMyStateSchema:
    """Tests for MyStateSchema Pydantic model."""

    def test_valid_schema(self):
        schema = MyStateSchema(input="test input", output="test output")
        assert schema.input == "test input"
        assert schema.output == "test output"

    def test_required_input(self):
        """Test that input is required."""
        with pytest.raises(ValidationError):
            MyStateSchema(output="test output")

    def test_output_optional(self):
        """Test that output is optional with default None."""
        schema = MyStateSchema(input="test input")
        assert schema.output is None

    def test_empty_strings_allowed(self):
        """Test that empty strings are valid."""
        schema = MyStateSchema(input="", output="")
        assert schema.input == ""
        assert schema.output == ""

    def test_serialization(self):
        """Test model can be serialized to dict."""
        schema = MyStateSchema(input="in", output="out")
        data = schema.model_dump()
        assert data == {"input": "in", "output": "out"}

    def test_from_dict(self):
        """Test model can be created from dict."""
        data = {"input": "test_in", "output": "test_out"}
        schema = MyStateSchema(**data)
        assert schema.input == "test_in"
        assert schema.output == "test_out"

    def test_unicode_support(self):
        """Test that unicode strings work."""
        schema = MyStateSchema(input="你好", output="مرحبا")
        assert schema.input == "你好"
        assert schema.output == "مرحبا"

    def test_multiline_strings(self):
        """Test that multiline strings work."""
        input_text = "Line 1\nLine 2\nLine 3"
        output_text = "Result 1\nResult 2"
        schema = MyStateSchema(input=input_text, output=output_text)
        assert "\n" in schema.input
        assert "\n" in schema.output
