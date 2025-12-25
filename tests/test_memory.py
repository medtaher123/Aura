from src.core.memory import format_chat_history, normalize_chat_messages


def test_normalize_chat_messages_filters_and_coerces():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": 123},
        {"role": "", "content": "skip"},
        "junk",
        ("user", "ok"),
    ]

    out = normalize_chat_messages(msgs)
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "123"},
        {"role": "user", "content": "ok"},
    ]


def test_format_chat_history_limits_tail():
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(20)]
    text = format_chat_history(msgs, max_messages=5)
    assert "User: m15" in text
    assert "User: m14" not in text


def test_format_chat_history_truncates_chars_keeps_recent():
    msgs = [
        {"role": "user", "content": "a" * 5000},
        {"role": "assistant", "content": "b" * 5000},
    ]
    text = format_chat_history(msgs, max_messages=10, max_chars=2000)
    assert len(text) <= 2000
    assert "Assistant:" in text
