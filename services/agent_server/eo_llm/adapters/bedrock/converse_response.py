"""Helpers for parsing Bedrock Converse API responses."""

from __future__ import annotations

from typing import Any


def extract_text_from_converse_response(response: dict[str, Any]) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    if not isinstance(content, list):
        return ""
    text_parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text.strip())
        citations_block = part.get("citationsContent")
        if isinstance(citations_block, dict):
            generated = citations_block.get("content")
            if isinstance(generated, list):
                for item in generated:
                    if isinstance(item, dict):
                        t = item.get("text")
                        if isinstance(t, str) and t.strip():
                            text_parts.append(t.strip())
    return "\n".join(text_parts).strip()


def extract_document_citations(response: dict[str, Any]) -> list[dict[str, Any]]:
    content = response.get("output", {}).get("message", {}).get("content", [])
    if not isinstance(content, list):
        return []
    citations: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        citations_block = part.get("citationsContent")
        if not isinstance(citations_block, dict):
            continue
        refs = citations_block.get("citations")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if isinstance(ref, dict):
                citations.append(ref)
    return citations
