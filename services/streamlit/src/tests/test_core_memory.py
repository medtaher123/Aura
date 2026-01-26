"""
Tests for core/memory.py - Chat message normalization and history formatting.
"""

import pytest

from src.core.memory import normalize_chat_messages, format_chat_history


class TestNormalizeChatMessages:
    """Tests for normalize_chat_messages function."""

    def test_empty_list_returns_empty(self):
        assert normalize_chat_messages([]) == []

    def test_none_returns_empty(self):
        assert normalize_chat_messages(None) == []

    def test_non_list_returns_empty(self):
        assert normalize_chat_messages("not a list") == []
        assert normalize_chat_messages(123) == []
        assert normalize_chat_messages({"key": "value"}) == []

    def test_dict_messages_normalized(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there!"}

    def test_tuple_messages_normalized(self):
        messages = [
            ("user", "Hello"),
            ("assistant", "Hi there!"),
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there!"}

    def test_list_pair_messages_normalized(self):
        messages = [
            ["user", "Hello"],
            ["assistant", "Hi there!"],
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there!"}

    def test_missing_role_skipped(self):
        messages = [
            {"content": "No role"},
            {"role": "user", "content": "Valid"},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_empty_role_skipped(self):
        messages = [
            {"role": "", "content": "Empty role"},
            {"role": "   ", "content": "Whitespace role"},
            {"role": "user", "content": "Valid"},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 1

    def test_none_content_skipped(self):
        messages = [
            {"role": "user", "content": None},
            {"role": "user", "content": "Valid"},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 1

    def test_empty_content_skipped(self):
        messages = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "   "},
            {"role": "user", "content": "Valid"},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 1

    def test_non_string_content_converted(self):
        messages = [
            {"role": "user", "content": 12345},
            {"role": "user", "content": ["a", "b"]},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 2
        assert result[0]["content"] == "12345"
        assert result[1]["content"] == "['a', 'b']"

    def test_whitespace_trimmed(self):
        messages = [
            {"role": "  user  ", "content": "  Hello  "},
        ]
        result = normalize_chat_messages(messages)
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_unknown_roles_preserved(self):
        messages = [
            {"role": "system", "content": "System message"},
            {"role": "custom_role", "content": "Custom role message"},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "custom_role"

    def test_invalid_items_skipped(self):
        messages = [
            "just a string",
            123,
            None,
            {"role": "user", "content": "Valid"},
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 1

    def test_mixed_formats(self):
        messages = [
            {"role": "user", "content": "Dict format"},
            ("assistant", "Tuple format"),
            ["user", "List format"],
        ]
        result = normalize_chat_messages(messages)
        assert len(result) == 3


class TestFormatChatHistory:
    """Tests for format_chat_history function."""

    def test_empty_messages_returns_empty(self):
        assert format_chat_history([]) == ""
        assert format_chat_history(None) == ""

    def test_basic_formatting(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = format_chat_history(messages)
        assert "User: Hello" in result
        assert "Assistant: Hi there!" in result

    def test_role_capitalization(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "System msg"},
        ]
        result = format_chat_history(messages)
        assert "User: Hello" in result
        assert "System: System msg" in result

    def test_max_messages_limit(self):
        messages = [{"role": "user", "content": f"Message {i}"} for i in range(20)]
        result = format_chat_history(messages, max_messages=5)
        # Should only contain last 5 messages
        assert "Message 19" in result
        assert "Message 15" in result
        assert "Message 14" not in result

    def test_max_messages_zero_keeps_all(self):
        messages = [{"role": "user", "content": f"Message {i}"} for i in range(5)]
        result = format_chat_history(messages, max_messages=0)
        for i in range(5):
            assert f"Message {i}" in result

    def test_max_chars_truncation(self):
        messages = [
            {"role": "user", "content": "A" * 1000},
            {"role": "assistant", "content": "B" * 1000},
        ]
        result = format_chat_history(messages, max_chars=500)
        assert len(result) <= 500

    def test_max_chars_none_or_zero_no_truncation(self):
        messages = [{"role": "user", "content": "A" * 100}]
        result1 = format_chat_history(messages, max_chars=None)
        result2 = format_chat_history(messages, max_chars=0)
        assert len(result1) > 100
        assert len(result2) > 100

    def test_truncation_avoids_mid_line(self):
        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Second message"},
            {"role": "user", "content": "Third message"},
        ]
        result = format_chat_history(messages, max_chars=50)
        # Should not start mid-word after truncation
        assert not result.startswith("ssage")

    def test_default_parameters(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = format_chat_history(messages)
        assert "User: Hello" in result

    def test_preserves_multiline_content(self):
        messages = [
            {"role": "user", "content": "Line 1\nLine 2\nLine 3"},
        ]
        result = format_chat_history(messages)
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_handles_unicode(self):
        messages = [
            {"role": "user", "content": "Bonjour! 你好! مرحبا!"},
        ]
        result = format_chat_history(messages)
        assert "Bonjour!" in result
        assert "你好!" in result
        assert "مرحبا!" in result
