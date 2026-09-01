"""Human-in-the-loop pause/resume helpers.

Node execution blobs (tool call history, tool plans, location candidates) are
stored in ``conversations.pause_state.hitl_blobs`` — not in LangGraph channels.

Blobs for the *current* graph run are keyed by LangGraph ``thread_id``.
ContextVars cannot be used here: values set inside a LangGraph node are not
visible to the parent ``astream`` task (and the reverse is unreliable across
workers). A ``thread_id`` map survives both directions.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from src.db.models.message_attachments import (
    MessageAttachment,
    apply_attachments,
    parse_attachments,
)
from src.user_inputs import LocationUserInput

_DEFAULT_THREAD = "__default__"

# thread_id -> {node_name -> blob} registered before interrupt (pause turn).
_pending_pause_blobs: dict[str, dict[str, dict[str, Any]]] = {}

# thread_id -> {node_name -> blob} installed for a resume turn.
_resume_blobs: dict[str, dict[str, dict[str, Any]]] = {}

# thread_id -> attachment dumps for the current resume turn.
_resume_attachments: dict[str, list[dict[str, Any]]] = {}


def current_thread_id() -> str:
    """LangGraph ``thread_id`` for the running node, or a test default."""
    try:
        from langgraph.config import get_config

        conf = get_config().get("configurable") or {}
        thread_id = conf.get("thread_id")
        if isinstance(thread_id, str) and thread_id.strip():
            return thread_id.strip()
    except Exception:
        pass
    return _DEFAULT_THREAD


def register_pause_blob(
    node_name: str,
    blob: dict[str, Any],
    *,
    thread_id: str | None = None,
) -> None:
    """Record a node execution blob before ``interrupt()``."""
    key = thread_id or current_thread_id()
    store = dict(_pending_pause_blobs.get(key) or {})
    store[node_name] = dict(blob)
    _pending_pause_blobs[key] = store


def take_pause_blobs(thread_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Return and clear blobs registered for this thread during the pause turn."""
    key = thread_id or current_thread_id()
    blobs = dict(_pending_pause_blobs.pop(key, {}) or {})
    return blobs


def get_resume_blob(
    node_name: str,
    *,
    thread_id: str | None = None,
) -> dict[str, Any] | None:
    """Return this node's execution blob for the current resume turn, if any."""
    key = thread_id or current_thread_id()
    blobs = _resume_blobs.get(key) or {}
    raw = blobs.get(node_name)
    return dict(raw) if isinstance(raw, dict) else None


@contextmanager
def hitl_resume_context(
    blobs: dict[str, dict[str, Any]],
    *,
    attachments: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
) -> Iterator[None]:
    """Install execution blobs (and optional resume attachments) for one graph run."""
    key = thread_id or current_thread_id()
    previous_blobs = _resume_blobs.get(key)
    previous_attachments = _resume_attachments.get(key)
    _resume_blobs[key] = {
        name: dict(blob) for name, blob in blobs.items() if isinstance(blob, dict)
    }
    _resume_attachments[key] = [
        dict(item) for item in (attachments or []) if isinstance(item, dict)
    ]
    try:
        yield
    finally:
        if previous_blobs is None:
            _resume_blobs.pop(key, None)
        else:
            _resume_blobs[key] = previous_blobs
        if previous_attachments is None:
            _resume_attachments.pop(key, None)
        else:
            _resume_attachments[key] = previous_attachments


def get_resume_attachments(*, thread_id: str | None = None) -> list[dict[str, Any]]:
    """Attachment dumps for the current resume turn (empty when not resuming)."""
    key = thread_id or current_thread_id()
    return list(_resume_attachments.get(key) or [])


def get_resume_blobs(*, thread_id: str | None = None) -> dict[str, dict[str, Any]]:
    """All node blobs installed for the current resume turn."""
    key = thread_id or current_thread_id()
    return {
        name: dict(blob)
        for name, blob in (_resume_blobs.get(key) or {}).items()
        if isinstance(blob, dict)
    }


def resume_state_patch(*, thread_id: str | None = None) -> dict[str, Any]:
    """Graph-state fields derived from resume attachments (not applied via Command)."""
    attachments = get_resume_attachments(thread_id=thread_id)
    if not attachments:
        return {}
    return state_update_from_attachments(
        attachments,
        get_resume_blobs(thread_id=thread_id),
    )


def hydrate_state_from_resume(s: Any) -> Any:
    """Merge resume attachment effects into a state model (in-node only)."""
    from eo_llm.graph.state import dump_state, validate_state

    patch = resume_state_patch()
    if not patch:
        return s
    return validate_state({**dump_state(s), **patch})


def resume_attachments(resume: dict[str, Any]) -> list[Any]:
    """Attachment list from a ``Command(resume=...)`` value."""
    data = resume.get("data") if isinstance(resume.get("data"), dict) else resume
    if not isinstance(data, dict):
        return []
    raw = data.get("attachments")
    return list(raw) if isinstance(raw, list) else []


def client_payload_needs_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract websocket ``needs_input`` from an interrupt client payload."""
    data = payload.get("data")
    if isinstance(data, dict):
        needs = data.get("needs_input")
        if isinstance(needs, dict):
            return dict(needs)
    needs = payload.get("needs_input")
    if isinstance(needs, dict):
        return dict(needs)
    return {}


def state_update_from_attachments(
    attachments: list[MessageAttachment] | list[dict[str, Any]] | None,
    hitl_blobs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a partial state patch from resume attachments + optional HITL blobs.

    Applied inside nodes via ``hydrate_state_from_resume`` / ``GraphNode.__call__``.
    Do not pass this through ``Command(update=...)`` — that races with ``dump_state``
    returns and raises ``InvalidUpdateError``.
    """
    from eo_llm.graph.nodes.helpers import resolved_location_from_candidate

    parsed = parse_attachments(attachments)  # type: ignore[arg-type]
    if not parsed:
        return {}

    state_dict: dict[str, Any] = {}
    apply_attachments(parsed, state_dict)

    blobs = hitl_blobs or {}
    location_blob = blobs.get("location_gate") or {}
    candidates = location_blob.get("location_candidates")
    if isinstance(candidates, list) and candidates:
        location_attachment = next(
            (a for a in parsed if getattr(a, "type", None) == "location"),
            None,
        )
        if location_attachment is not None:
            idx = LocationUserInput.match_candidate_index(
                candidates, location_attachment
            )
            if 0 <= idx < len(candidates):
                candidate = candidates[idx]
                if isinstance(candidate, dict):
                    state_dict["location_candidates"] = list(candidates)
                    state_dict["location_query"] = str(
                        location_blob.get("location_query")
                        or state_dict.get("location_query")
                        or ""
                    )
                    state_dict["resolved_location"] = (
                        resolved_location_from_candidate(candidate).model_dump(
                            mode="python"
                        )
                    )

    return state_dict


def state_update_from_resume_dict(
    resume: dict[str, Any],
    hitl_blobs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a graph-state patch from a resume payload and stored blobs."""
    return state_update_from_attachments(
        parse_attachments(resume_attachments(resume)),
        hitl_blobs,
    )
