"""Agent profile tool filtering."""

from __future__ import annotations

from contextvars import ContextVar

from src.db.models.agent_profile import AgentProfile

DEFAULT_AGENT_PROFILE_SLUG = "aura-default"

_agent_profile_slug: ContextVar[str] = ContextVar(
    "agent_profile_slug", default=DEFAULT_AGENT_PROFILE_SLUG
)
_cached_profile: AgentProfile | None = None


def set_agent_profile_slug(slug: str) -> None:
    _agent_profile_slug.set(slug or DEFAULT_AGENT_PROFILE_SLUG)


def get_agent_profile_slug() -> str:
    return _agent_profile_slug.get()


def set_cached_agent_profile(profile: AgentProfile | None) -> None:
    global _cached_profile
    _cached_profile = profile


def get_cached_agent_profile() -> AgentProfile | None:
    return _cached_profile


def resolve_allowed_tools(
    domain_tools: list[str],
    profile: AgentProfile | None,
) -> list[str]:
    """Intersect domain tool list with agent profile bindings.

    When the profile has no bindings, domain tools are returned unchanged.
    """
    if profile is None or not profile.tool_bindings:
        return domain_tools

    allowed = {
        binding.tool_definition.name
        for binding in profile.tool_bindings
        if binding.enabled and binding.tool_definition.enabled
    }
    if not allowed:
        return domain_tools
    return [name for name in domain_tools if name in allowed]


def profile_allowed_tool_names(profile: AgentProfile | None) -> set[str] | None:
    """Return allowed tool names for a profile, or None if unrestricted."""
    if profile is None or not profile.tool_bindings:
        return None
    allowed = {
        binding.tool_definition.name
        for binding in profile.tool_bindings
        if binding.enabled and binding.tool_definition.enabled
    }
    return allowed if allowed else None
