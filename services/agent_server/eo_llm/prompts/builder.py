"""Prompt composition helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eo_llm.prompts.persona import AURA_PERSONA


def _join_sections(*sections: str) -> str:
    parts = [s.strip() for s in sections if s and s.strip()]
    return "\n\n".join(parts)


def _format_rules(title: str, rules: tuple[str, ...]) -> str:
    if not rules:
        return ""
    lines = "\n".join(f"- {rule}" for rule in rules)
    return f"{title}:\n{lines}"


def _format_context(**context: Any) -> str:
    lines: list[str] = []
    for key, value in context.items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            import json

            rendered = json.dumps(value, ensure_ascii=True, default=str)
        else:
            rendered = str(value).strip()
        if not rendered:
            continue
        label = key.replace("_", " ").strip().capitalize()
        lines.append(f"{label}: {rendered}")
    return "\n".join(lines)


@dataclass(frozen=True)
class PromptSpec:
    """Composable prompt definition for the system message."""

    role: str
    task: str
    rules: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    include_persona: bool = True
    include_schema_rules: bool = False

    def system(
        self,
        *,
        persona: str = AURA_PERSONA,
        extra_rules: tuple[str, ...] = (),
    ) -> str:
        sections: list[str] = []
        if self.include_persona:
            sections.append(persona)
        sections.append(self.role)
        sections.append(self.task)
        all_rules = (*self.rules, *extra_rules)
        rules_block = _format_rules("Rules", all_rules)
        if rules_block:
            sections.append(rules_block)
        if self.include_schema_rules:
            from eo_llm.prompts.shared.schema import SCHEMA_OUTPUT_RULES

            sections.append(_format_rules("Output", SCHEMA_OUTPUT_RULES))
        if self.examples:
            sections.append("Examples:\n" + "\n\n".join(self.examples))
        return _join_sections(*sections)


def render_system(spec: PromptSpec, **context: Any) -> str:
    """Return a system prompt from a spec plus optional labeled context."""
    return _join_sections(spec.system(), _format_context(**context))
