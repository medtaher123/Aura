"""Build compact evidence digests for finalizer consumption."""

from __future__ import annotations

from typing import Any

MAX_DIGEST_CHARS = 2000
MAX_MESSAGE_CHARS = 220
MAX_DATA_DEPTH = 3
MAX_SCALAR_CHARS = 100
MAX_LIST_PREVIEW = 5

# Keys omitted from digest (rendering payloads, large blobs, UI-only fields).
_SKIP_DATA_KEYS = frozenset(
    {
        "artifacts",
        "maps",
        "thumbnails",
        "urls",
        "bbox",
        "geometry",
        "coordinates",
        "vector_layers",
        "view_state",
        "candidates",
        "resume_patch",
        "available_days",
    }
)

# When present, these string fields are surfaced first at each dict level.
_PREFERRED_LABEL_KEYS = ("headline", "summary", "title", "label", "message")


def _domain_result_as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        return dump(mode="python")
    return {}


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        rounded = round(value, 4)
        return str(int(rounded)) if rounded == int(rounded) else str(rounded)
    text = str(value).strip()
    if len(text) > MAX_SCALAR_CHARS:
        return text[: MAX_SCALAR_CHARS - 3] + "..."
    return text


def _summarize_list(items: list[Any], *, indent: str, depth: int) -> list[str]:
    if not items:
        return [f"{indent}(empty)"]

    if all(isinstance(item, (str, int, float, bool)) or item is None for item in items):
        preview = ", ".join(_format_scalar(item) for item in items[:MAX_LIST_PREVIEW])
        suffix = ""
        if len(items) > MAX_LIST_PREVIEW:
            suffix = f" (+{len(items) - MAX_LIST_PREVIEW} more)"
        return [f"{indent}[{len(items)}]: {preview}{suffix}"]

    return [f"{indent}[{len(items)} items]"]


def _summarize_dict(data: dict[str, Any], *, indent: str, depth: int) -> list[str]:
    if depth > MAX_DATA_DEPTH:
        return [f"{indent}..."]

    lines: list[str] = []

    for label_key in _PREFERRED_LABEL_KEYS:
        label_value = data.get(label_key)
        if isinstance(label_value, str) and label_value.strip():
            lines.append(f"{indent}{label_key}: {label_value.strip()[:MAX_SCALAR_CHARS]}")

    for key, value in data.items():
        if key in _SKIP_DATA_KEYS or key in _PREFERRED_LABEL_KEYS:
            continue
        lines.extend(_summarize_field(key, value, indent=indent, depth=depth))

    return lines


def _summarize_field(key: str, value: Any, *, indent: str, depth: int) -> list[str]:
    if value is None:
        return []

    if isinstance(value, dict):
        if not value:
            return []
        nested = _summarize_dict(value, indent=f"{indent}  ", depth=depth + 1)
        if not nested:
            return []
        return [f"{indent}{key}:"] + nested

    if isinstance(value, list):
        nested = _summarize_list(value, indent=f"{indent}  ", depth=depth + 1)
        return [f"{indent}{key}:"] + nested

    return [f"{indent}{key}: {_format_scalar(value)}"]


def _format_context_fields(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("city", "country", "start_date", "end_date"):
        value = result.get(key)
        if value is not None and str(value).strip():
            lines.append(f"  {key}: {_format_scalar(value)}")
    return lines


def _format_execution(tool_name: str, result: dict[str, Any]) -> list[str]:
    if not isinstance(result, dict):
        return []

    lines = [f"- {tool_name}"]

    message = result.get("message")
    if isinstance(message, str) and message.strip():
        lines.append(f"  message: {message.strip()[:MAX_MESSAGE_CHARS]}")

    lines.extend(_format_context_fields(result))

    data = result.get("data")
    if not isinstance(data, dict) or not data:
        return lines

    needs_input = data.get("needs_input")
    if isinstance(needs_input, dict) and needs_input:
        lines.append(f"  status: user_input_required kinds={list(needs_input.keys())}")
        return lines
    if data.get("needs_location_confirmation"):
        lines.append("  status: user_input_required kinds=['location']")
        return lines

    data_lines = _summarize_dict(data, indent="  ", depth=0)
    if data_lines:
        lines.append("  data:")
        lines.extend(data_lines)

    return lines


def build_domain_evidence_digest(domain_results: dict[str, Any]) -> str:
    """Summarize tool executions into compact text for the finalizer."""
    sections: list[str] = []

    for domain_name, raw_result in domain_results.items():
        result = _domain_result_as_dict(raw_result)
        if not result:
            continue

        lines = [f"[{domain_name}]"]
        executions = result.get("executions")
        if isinstance(executions, list) and executions:
            for execution in executions:
                if not isinstance(execution, dict):
                    continue
                if execution.get("status") != "success":
                    continue
                tool_name = str(execution.get("tool_name") or "unknown_tool")
                step_result = execution.get("result")
                if isinstance(step_result, dict):
                    lines.extend(_format_execution(tool_name, step_result))
        else:
            top_result = result.get("result")
            tool_name = str(result.get("tool") or "domain_tool")
            if isinstance(top_result, dict):
                lines.extend(_format_execution(tool_name, top_result))

        if len(lines) > 1:
            sections.append("\n".join(lines))

    digest = "\n\n".join(sections).strip()
    if not digest:
        return "No structured domain evidence available."
    return digest[:MAX_DIGEST_CHARS]
