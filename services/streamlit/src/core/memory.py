from __future__ import annotations

from typing import Any, Iterable, Mapping


def normalize_chat_messages(messages: Any) -> list[dict]:
    """Normalize various message shapes into [{role, content}, ...].

    Expected roles: 'user' | 'assistant' | 'system'.
    Unknown roles are preserved as strings.
    """

    if not isinstance(messages, list):
        return []

    normalized: list[dict] = []
    for item in messages:
        if isinstance(item, Mapping):
            role = item.get("role")
            content = item.get("content")
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            role, content = item
        else:
            continue

        if not isinstance(role, str) or not role.strip():
            continue
        if content is None:
            continue

        if not isinstance(content, str):
            content = str(content)

        content = content.strip()
        if not content:
            continue

        normalized.append({"role": role.strip(), "content": content})

    return normalized


# Per-message content cap so one huge assistant message doesn't blow the prompt (Bedrock 200k limit)
MAX_MESSAGE_CONTENT_CHARS = 2500


def format_chat_history(
    messages: Any,
    *,
    max_messages: int = 12,
    max_chars: int = 6000,
) -> str:
    """Format recent chat history as plain text for prompt injection.

    - Keeps only the last `max_messages` messages.
    - Truncates each message's content to MAX_MESSAGE_CONTENT_CHARS.
    - Truncates total to fit within `max_chars`.
    """

    norm = normalize_chat_messages(messages)
    if not norm:
        return ""

    tail = norm[-max_messages:] if max_messages > 0 else norm

    lines: list[str] = []
    for m in tail:
        role = m.get("role", "")
        content = m.get("content", "")
        if len(content) > MAX_MESSAGE_CONTENT_CHARS:
            content = content[: MAX_MESSAGE_CONTENT_CHARS - 20].rstrip() + "… [truncated]"
        lines.append(f"{role.capitalize()}: {content}")

    text = "\n".join(lines).strip()
    if not text:
        return ""

    if max_chars is not None and max_chars > 0 and len(text) > max_chars:
        # keep the most recent portion
        text = text[-max_chars:]
        # avoid starting mid-line when possible
        cut = text.find("\n")
        if 0 <= cut <= 200:
            text = text[cut + 1 :]
        text = text.strip()

    return text
