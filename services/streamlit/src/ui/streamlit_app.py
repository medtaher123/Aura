"""Streamlit UI for MetaplanetLLM.

Renders assistant responses, including map artifacts (HTML or Pydeck specs).
"""

import io
import html
import os
import queue
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional
from urllib.parse import urlparse
from typing_extensions import TypedDict

import numpy as np
import streamlit as st
import pydeck as pdk
import requests
from PIL import Image
from dotenv import load_dotenv
from streamlit.delta_generator import DeltaGenerator

# Ensure project root is on sys.path so absolute imports work when running via
# `streamlit run src/ui/streamlit_app.py`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load local env vars (e.g., MAPTILER_API_KEY) from repo `.env`.
load_dotenv(PROJECT_ROOT / ".env", override=False)

from src.clients.agent_ws_client import LocationOption, get_osm_type_prefix  # noqa: E402
from src.clients.agent_adapter import (  # noqa: E402
    get_shared_agent_adapter,
    AgentResponse,
    ToolArtifacts,
)
from src.core.logger import get_logger  # noqa: E402
from src.services.document_service import extract_text_from_pdf_bytes  # noqa: E402
from src.auth import (  # noqa: E402
    auth_enabled,
    render_login_gate,
    render_logout_control,
)

logger = get_logger(__name__)


def _crop_to_valid_region(rgb: np.ndarray, min_fraction: float = 0.05) -> np.ndarray:
    """Crop to the bounding box of non-black pixels so previews are not mostly black borders."""
    if rgb.size == 0 or rgb.ndim != 3:
        return rgb
    has_data = (rgb > 0).any(axis=-1)
    if not np.any(has_data):
        return rgb
    rows = np.where(has_data.any(axis=1))[0]
    cols = np.where(has_data.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return rgb
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    cropped = rgb[r0:r1, c0:c1]
    if cropped.size < min_fraction * rgb.size:
        return rgb
    return cropped




@st.cache_data(ttl=3600, max_entries=256)
def _cog_url_to_png_bytes(url: str, max_size: int = 400) -> bytes | None:
    """Fetch a COG from url, read a small overview as RGB, return PNG bytes for in-UI display. Returns None on failure or if URL is not allowlisted."""
    try:
        parsed = urlparse(url)
        if parsed.netloc not in _COG_PREVIEW_ALLOWED_NETLOCS:
            return None
        import rasterio
        with rasterio.open(url) as src:
            nbands = src.count
            h, w = src.height, src.width
            if h <= 0 or w <= 0:
                return None
            scale = min(max_size / max(h, w), 1.0)
            out_h, out_w = max(1, int(h * scale)), max(1, int(w * scale))
            nodata = getattr(src, "nodata", None)
            if nbands >= 3:
                arr = src.read([1, 2, 3], out_shape=(3, out_h, out_w))
                arr = np.transpose(arr, (1, 2, 0))
            else:
                arr = src.read(1, out_shape=(out_h, out_w))
                arr = np.stack([arr, arr, arr], axis=-1)
            arr = np.nan_to_num(arr, nan=0, posinf=0, neginf=0).astype(np.float64)
            mask = None
            if nodata is not None:
                mask = (arr == nodata).any(axis=-1)
            else:
                mid = arr[:, :, 0] if arr.ndim == 3 else arr
                if np.sum(mid == 0) > 0.5 * mid.size:
                    mask = (arr == 0).any(axis=-1) if arr.ndim == 3 else (arr == 0)
            if mask is not None:
                arr[mask] = np.nan
            p_low, p_high = 2.0, 98.0
            out = np.zeros((out_h, out_w, 3), dtype=np.uint8)
            for c in range(3):
                band = arr[:, :, c]
                valid = band[~np.isnan(band)]
                if valid.size == 0:
                    continue
                lo, hi = np.nanpercentile(band, [p_low, p_high])
                if hi > lo:
                    scaled = (255 * (band - lo) / (hi - lo)).clip(0, 255).astype(np.uint8)
                else:
                    scaled = np.clip(band.astype(np.uint8), 0, 255)
                out[:, :, c] = np.where(np.isnan(band), 0, scaled)
            out = _crop_to_valid_region(out)
            pil = Image.fromarray(out)
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        logger.debug("COG preview failed for %s: %s", url[:80], e)
        return None


MAPS_DIR = PROJECT_ROOT / "src" / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

from src.services import detect_and_translate_to_english, translate_from_english  # noqa: E402

logger.info("Streamlit app starting...")


# Type definitions for chat messages
ToolRunStatus = Literal["running", "success", "error", "skipped"]


class UserMessage(TypedDict):
    """User message in chat history."""

    role: Literal["user"]
    content: str


class ToolCallRecord(TypedDict, total=False):
    """Persisted tool execution row for chat history."""

    tool_name: str
    status: ToolRunStatus
    step_id: str | None
    domain: str | None
    execution_time_seconds: float | None
    detail: str | None


class AssistantMessage(TypedDict, total=False):
    """Assistant message in chat history."""

    role: Literal["assistant"]
    content: str
    artifacts: ToolArtifacts
    error: bool
    tool_calls: list[ToolCallRecord]


# Union type for all message types
Message = UserMessage | AssistantMessage


def _confirmed_location_from_cache(display: str, token: Optional[str]) -> dict:
    """Build a confirmed-location payload from a cached disambiguation token.

    Tokens look like ``@osm_id:R4479752`` or ``@place_id:397136633``. Parsing the
    identifier lets the backend match it against the fresh candidate list when
    auto-confirming a previously chosen location.
    """
    loc: dict = {"name": display or "", "coordinates": [0, 0]}
    if not isinstance(token, str):
        return loc
    if token.startswith("@osm_id:") and len(token) > len("@osm_id:"):
        rest = token[len("@osm_id:") :]
        prefix, digits = rest[:1], rest[1:]
        osm_types = {"R": "relation", "W": "way", "N": "node"}
        if prefix in osm_types and digits.isdigit():
            loc["osm_id"] = int(digits)
            loc["osm_type"] = osm_types[prefix]
            loc["osm_type_prefix"] = prefix
    elif token.startswith("@place_id:"):
        digits = token[len("@place_id:") :]
        if digits.isdigit():
            loc["place_id"] = int(digits)
    return loc


def _invoke_agent_unified(
    executor,
    english_query: str,
    chat_history=None,
    resume=None,
    confirmed_location=None,
    conversation_id=None,
    stream_callback=None,
    language=None,
    document_context=None,
) -> AgentResponse:
    """
    Invoke the remote agent via WebSocket.

    Returns AgentResponse with: message, artifacts, error, needs_location_confirmation,
    location_options, pause_state, raw_data
    """
    return executor.invoke(
        message=english_query,
        chat_history=chat_history,
        document_context=document_context,
        resume=resume,
        confirmed_location=confirmed_location,
        conversation_id=conversation_id,
        stream_callback=stream_callback,
        language=language,
    )


def _invoke_agent_with_streaming_display(
    executor,
    *,
    message_placeholder: DeltaGenerator,
    tools_placeholder: DeltaGenerator | None = None,
    trace_callback: Callable[[dict], None] | None = None,
    tools_callback: Callable[[dict], None] | None = None,
    english_query: str = "",
    chat_history=None,
    resume=None,
    confirmed_location=None,
    conversation_id=None,
    language=None,
    document_context=None,
) -> AgentResponse:
    """Run the agent on a worker thread and render stream events on the main thread."""
    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()

    def stream_callback(evt: dict) -> None:
        if not isinstance(evt, dict):
            return
        if evt.get("type") == "token":
            content = evt.get("content")
            if isinstance(content, str) and content:
                event_queue.put(("token", content))
            return
        event_queue.put(("event", evt))

    def run_agent() -> AgentResponse:
        return _invoke_agent_unified(
            executor,
            english_query,
            chat_history=chat_history,
            resume=resume,
            confirmed_location=confirmed_location,
            conversation_id=conversation_id,
            stream_callback=stream_callback,
            language=language,
            document_context=document_context,
        )

    def drain_events() -> None:
        nonlocal streamed, show_cursor
        while True:
            try:
                kind, payload = event_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "token" and isinstance(payload, str):
                streamed += payload
                show_cursor = True
                message_placeholder.markdown(streamed + "▌")
            elif kind == "event" and isinstance(payload, dict):
                if tools_callback and _is_tool_progress_event(payload):
                    tools_callback(payload)
                elif trace_callback:
                    trace_callback(payload)

    streamed = ""
    show_cursor = False

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_agent)
        while True:
            drain_events()
            if future.done():
                drain_events()
                break
            time.sleep(0.02)

        result = future.result()

    final_text = (result.message or streamed).strip()
    if final_text:
        message_placeholder.markdown(final_text)
    elif show_cursor:
        message_placeholder.empty()

    return result


def _default_pydeck_map_style() -> str:
    """Pick a basemap style without hardcoding secrets."""
    if os.getenv("MAPBOX_API_KEY") or os.getenv("MAPBOX_ACCESS_TOKEN"):
        return "mapbox://styles/mapbox/light-v10"

    maptiler_key = os.getenv("MAPTILER_API_KEY")
    if maptiler_key:
        return f"https://api.maptiler.com/maps/streets/style.json?key={maptiler_key}"

    return "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"


def _coerce_view_state(view_state: dict) -> pdk.ViewState:
    latitude = float(view_state.get("latitude", 0.0) or 0.0)
    longitude = float(view_state.get("longitude", 0.0) or 0.0)
    zoom = float(view_state.get("zoom", 2.0) or 2.0)
    bearing = float(view_state.get("bearing", 0.0) or 0.0)
    pitch = float(view_state.get("pitch", 0.0) or 0.0)
    return pdk.ViewState(
        latitude=latitude,
        longitude=longitude,
        zoom=zoom,
        bearing=bearing,
        pitch=pitch,
    )


def _render_pydeck_map_spec(item: dict) -> None:
    view_state_raw = item.get("view_state") or {}
    if not isinstance(view_state_raw, dict):
        view_state_raw = {}

    layers: list[pdk.Layer] = []

    # Backwards-compatible shorthand: {points: [...], ...}
    points = item.get("points")
    if isinstance(points, list):
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=points,
                get_position=item.get("get_position", "[lon, lat]"),
                get_radius=item.get("radius", 50),
                radius_units=item.get("radius_units", "meters"),
                radius_min_pixels=item.get("radius_min_pixels", 3),
                radius_max_pixels=item.get("radius_max_pixels", 15),
                get_fill_color=item.get("fill_color", [255, 0, 0, 160]),
                pickable=bool(item.get("pickable", True)),
            )
        )

    # Generic form: {layers: [{type, data, ...}, ...]}
    layer_specs = item.get("layers")
    if isinstance(layer_specs, list):
        for spec in layer_specs:
            if not isinstance(spec, dict):
                continue
            layer_type = spec.get("type")
            data = spec.get("data")
            if not isinstance(layer_type, str) or not layer_type.strip():
                continue

            props = dict(spec)
            props.pop("type", None)
            props.pop("data", None)
            if "pickable" not in props:
                props["pickable"] = True

            try:
                layers.append(pdk.Layer(layer_type, data=data, **props))
            except Exception:
                # Skip invalid layer specs rather than crashing the whole UI.
                continue

    tooltip = item.get("tooltip")
    if not isinstance(tooltip, dict):
        tooltip = {"text": ""}

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=_coerce_view_state(view_state_raw),
        map_style=item.get("map_style") or _default_pydeck_map_style(),
        tooltip=tooltip,  # type: ignore
    )
    st.pydeck_chart(deck, use_container_width=True, height=item.get("height", 450))


def _shorten(text: str, *, max_len: int = 220) -> str:
    if not isinstance(text, str):
        text = str(text)
    s = " ".join(text.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


_TOOL_STATUS_CSS = """
@keyframes metaplanet-tool-spin {
  to { transform: rotate(360deg); }
}
.metaplanet-tool-spin {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #22c55e;
  border-top-color: transparent;
  border-radius: 50%;
  animation: metaplanet-tool-spin 0.85s linear infinite;
  vertical-align: middle;
}
.metaplanet-tool-dot-success {
  display: inline-block;
  width: 14px;
  height: 14px;
  background: #22c55e;
  border-radius: 50%;
  vertical-align: middle;
}
.metaplanet-tool-dot-error {
  display: inline-block;
  width: 14px;
  height: 14px;
  background: #ef4444;
  border-radius: 50%;
  vertical-align: middle;
}
.metaplanet-tool-dot-skipped {
  display: inline-block;
  width: 14px;
  height: 14px;
  background: #f59e0b;
  border-radius: 50%;
  vertical-align: middle;
}
"""

@dataclass
class _ToolCallState:
    key: str
    tool_name: str
    status: ToolRunStatus = "running"
    step_id: str | None = None
    domain: str | None = None
    execution_time_seconds: float | None = None
    detail: str | None = None
    order: int = 0


def _format_execution_time(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value < 1:
        return f"{value:.2f}s"
    return f"{value:.1f}s"


def _resolve_tool_step_id(evt: dict) -> str | None:
    step_id = evt.get("step_id")
    if isinstance(step_id, str) and step_id.strip():
        return step_id.strip()
    tool_input = evt.get("tool_input")
    if isinstance(tool_input, dict):
        nested = tool_input.get("step_id")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def _resolve_tool_domain(evt: dict) -> str | None:
    domain = evt.get("domain")
    if isinstance(domain, str) and domain.strip():
        return domain.strip()
    tool_input = evt.get("tool_input")
    if isinstance(tool_input, dict):
        nested = tool_input.get("domain")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def _tool_call_key(evt: dict, *, order: int) -> str:
    step_id = _resolve_tool_step_id(evt)
    if step_id:
        return step_id
    tool_name = str(evt.get("tool_name") or "tool")
    return f"{tool_name}:{order}"


def _tool_status_from_event(evt: dict) -> ToolRunStatus:
    phase = evt.get("phase")
    status = evt.get("status")
    if phase == "running":
        return "running"
    if status == "skipped":
        return "skipped"
    if bool(evt.get("error")) or status == "error":
        return "error"
    return "success"


def _tool_status_meta(tool: _ToolCallState) -> str:
    if tool.status == "running":
        return "Running…"
    if tool.status == "success":
        return _format_execution_time(tool.execution_time_seconds) or "Done"
    if tool.status == "error":
        return "Error"
    return "Skipped"


def _tool_status_icon_html(status: ToolRunStatus) -> str:
    if status == "running":
        return '<span class="metaplanet-tool-spin"></span>'
    if status == "success":
        return '<span class="metaplanet-tool-dot-success"></span>'
    if status == "error":
        return '<span class="metaplanet-tool-dot-error"></span>'
    return '<span class="metaplanet-tool-dot-skipped"></span>'


def _tool_call_to_record(tool: _ToolCallState) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name=tool.tool_name,
        status=tool.status,
        step_id=tool.step_id,
        domain=tool.domain,
        execution_time_seconds=tool.execution_time_seconds,
        detail=tool.detail,
    )


def _record_to_tool_call(record: ToolCallRecord) -> _ToolCallState:
    tool_name = record.get("tool_name") or "tool"
    return _ToolCallState(
        key=record.get("step_id") or tool_name,
        tool_name=tool_name,
        status=record.get("status", "success"),
        step_id=record.get("step_id"),
        domain=record.get("domain"),
        execution_time_seconds=record.get("execution_time_seconds"),
        detail=record.get("detail"),
    )


def _is_tool_progress_event(evt: dict) -> bool:
    event_type = evt.get("type")
    if event_type == "data_agent_step":
        return True
    if event_type == "stage" and evt.get("stage") in {"tool_call", "data_agent"}:
        return True
    return False


def _normalize_tool_progress_event(evt: dict) -> dict | None:
    event_type = evt.get("type")
    if event_type == "data_agent_step":
        return evt
    if event_type == "stage" and evt.get("stage") in {"tool_call", "data_agent"}:
        return {
            "type": "data_agent_step",
            "phase": "running",
            "tool_name": "tools",
            "step_id": "__pending__",
        }
    return None


def _render_tool_status_box(tools: list[_ToolCallState]) -> None:
    if not tools:
        return

    with st.container(border=True):
        st.markdown("**Tools**")
        for index, tool in enumerate(sorted(tools, key=lambda item: item.order)):
            if index > 0:
                st.divider()
            icon_col, body_col, meta_col = st.columns([0.06, 0.64, 0.30], gap="small")
            with icon_col:
                st.markdown(_tool_status_icon_html(tool.status), unsafe_allow_html=True)
            with body_col:
                st.markdown(f"**{tool.tool_name}**")
                subtitle_parts: list[str] = []
                if tool.domain:
                    subtitle_parts.append(tool.domain)
                if tool.step_id and tool.step_id != "__pending__":
                    subtitle_parts.append(tool.step_id)
                if tool.detail and tool.status in {"error", "skipped"}:
                    subtitle_parts.append(_shorten(tool.detail, max_len=120))
                if subtitle_parts:
                    st.caption(" · ".join(subtitle_parts))
            with meta_col:
                st.markdown(
                    f"<div style='text-align:right;font-size:0.85rem;'>{html.escape(_tool_status_meta(tool))}</div>",
                    unsafe_allow_html=True,
                )


def _make_tool_status_tracker(
    tools_placeholder: DeltaGenerator,
) -> tuple[Callable[[dict], None], Callable[[], list[ToolCallRecord]]]:
    tools_by_key: dict[str, _ToolCallState] = {}
    next_order = 0

    def _find_running_key(tool_name: str) -> str | None:
        for key, tool in tools_by_key.items():
            if tool.tool_name == tool_name and tool.status == "running":
                return key
        return None

    def _render() -> None:
        tools = sorted(tools_by_key.values(), key=lambda item: item.order)
        tools_placeholder.empty()
        if not tools:
            return
        with tools_placeholder.container():
            _render_tool_status_box(tools)

    def callback(evt: dict) -> None:
        nonlocal next_order
        normalized = _normalize_tool_progress_event(evt)
        if normalized is None:
            return

        phase = normalized.get("phase")
        tool_name = normalized.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            return

        step_id = _resolve_tool_step_id(normalized)
        domain = _resolve_tool_domain(normalized)

        if phase == "running":
            if step_id == "__pending__" and tools_by_key:
                return
            next_order += 1
            key = _tool_call_key(normalized, order=next_order)
            tools_by_key[key] = _ToolCallState(
                key=key,
                tool_name=tool_name,
                status="running",
                step_id=step_id,
                domain=domain,
                order=next_order,
            )
            _render()
            return

        if phase != "done":
            return

        if step_id == "__pending__":
            return

        key = step_id or _find_running_key(tool_name) or _tool_call_key(
            normalized, order=next_order
        )
        if key not in tools_by_key:
            next_order += 1
            tools_by_key[key] = _ToolCallState(
                key=key,
                tool_name=tool_name,
                order=next_order,
            )

        tool = tools_by_key[key]
        if tool.step_id == "__pending__":
            tools_by_key.pop(key, None)
            next_order += 1
            key = step_id or _tool_call_key(normalized, order=next_order)
            tools_by_key[key] = _ToolCallState(
                key=key,
                tool_name=tool_name,
                order=next_order,
            )
            tool = tools_by_key[key]

        tool.tool_name = tool_name
        tool.step_id = step_id or tool.step_id
        tool.domain = domain or tool.domain
        tool.status = _tool_status_from_event(normalized)
        tool.execution_time_seconds = normalized.get("execution_time_seconds")
        observation = normalized.get("observation")
        if isinstance(observation, str) and observation.strip():
            tool.detail = observation.strip()
        elif tool.status == "skipped":
            tool.detail = "Missing required inputs"
        _render()

    def snapshot() -> list[ToolCallRecord]:
        return [
            _tool_call_to_record(tool)
            for tool in sorted(tools_by_key.values(), key=lambda item: item.order)
        ]

    return callback, snapshot


def _make_streaming_event_handler(
    *,
    tools_placeholder: DeltaGenerator,
    trace_placeholder: DeltaGenerator,
) -> tuple[Callable[[dict], None], Callable[[dict], None], Callable[[], list[ToolCallRecord]]]:
    tool_tracker, tool_snapshot = _make_tool_status_tracker(tools_placeholder)
    trace_updater = _make_live_trace_updater(trace_placeholder)

    def tools_callback(evt: dict) -> None:
        tool_tracker(evt)

    def trace_callback(evt: dict) -> None:
        if _is_tool_progress_event(evt):
            return
        trace_updater(evt)

    return tools_callback, trace_callback, tool_snapshot


def _make_live_trace_updater(trace_placeholder: DeltaGenerator):
    lines: list[str] = []

    def push(line: str) -> None:
        nonlocal lines
        if not isinstance(line, str) or not line.strip():
            return
        lines.append(line.strip())
        # Keep it short and readable.
        tail = lines[-12:]
        trace_placeholder.empty()
        with trace_placeholder.container():
            for line in tail:
                st.caption(line)

    def callback(evt: dict) -> None:
        if not isinstance(evt, dict):
            return
        et = evt.get("type")

        if et == "orchestrator_plan":
            trace = evt.get("trace")
            if isinstance(trace, dict):
                push(
                    f"Orchestrator: needs_data={trace.get('needs_data')} needs_analysis={trace.get('needs_analysis')}"
                )
            return

        if et == "stage":
            msg = evt.get("message")
            if isinstance(msg, str) and msg.strip():
                push(msg)
            return

        if et == "data_agent_finalizing":
            msg = evt.get("message")
            if isinstance(msg, str) and msg.strip():
                push(msg)

    return callback


# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
st.set_page_config(page_title="STAC & Fire Chatbot", layout="wide")

# Make the whole application's font bold.
st.markdown(
    """
    <style>
    html, body, [class*="css"], [class*="st-"],
    .stApp, .stMarkdown, .stMarkdown *,
    p, span, div, label, li, a,
    h1, h2, h3, h4, h5, h6,
    button, input, textarea, select,
    .stButton button, .stTextInput input, .stTextArea textarea,
    .stChatMessage, .stChatMessage * {
        font-weight: 700 !important;
    }
    """
    + _TOOL_STATUS_CSS
    + """
    </style>
    """,
    unsafe_allow_html=True,
)

# Enforce Cognito Hosted UI login before rendering the app. When Cognito is
# not configured this is a no-op so local/dev usage keeps working.
cognito_tokens = render_login_gate()

logo = Image.open(
    Path(__file__).resolve().parent / "assets" / "metaplanet_sas_logo.jpeg"
)
st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
st.image(logo, width=150)
st.markdown("</div>", unsafe_allow_html=True)

st.title("🛰️🔥 Metaplanet Earth Agent")


def _augment_with_document(english_query: str) -> str:
    doc = st.session_state.get("document_text") or ""
    use_doc = bool(st.session_state.get("use_document", True))
    if use_doc and isinstance(doc, str) and doc.strip():
        return f"document:\n{doc}\n\nuser question:\n{english_query}".strip()
    return english_query


def _get_conversation_id_from_query_params() -> str | None:
    value = st.query_params.get("conversation_id")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _set_conversation_id_query_param(conversation_id: str) -> None:
    if _get_conversation_id_from_query_params() == conversation_id:
        return
    st.query_params["conversation_id"] = conversation_id


def _clear_conversation_id_query_param() -> None:
    if "conversation_id" in st.query_params:
        del st.query_params["conversation_id"]


def _store_conversation_id(conversation_id: str | None) -> None:
    if not conversation_id:
        return
    st.session_state.conversation_id = conversation_id
    _set_conversation_id_query_param(conversation_id)


def _store_conversation_title(
    conversation_id: str | None, conversation_title: str | None
) -> None:
    if not conversation_id or not conversation_title:
        return
    titles = st.session_state.get("conversation_titles")
    if not isinstance(titles, dict):
        titles = {}
    titles[conversation_id] = conversation_title
    st.session_state.conversation_titles = titles


def _agent_server_http_base_url(agent_url: str) -> str:
    if "://" not in agent_url:
        agent_url = f"http://{agent_url}"
    parsed = urlparse(agent_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme or "http")
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    if path.endswith("/ws/chat"):
        path = path[: -len("/ws/chat")]
    return f"{scheme}://{netloc}{path}".rstrip("/")


def _agent_server_headers(auth_token: str | None) -> dict[str, str]:
    if not auth_token:
        return {}
    return {"Authorization": f"Bearer {auth_token}"}


def _list_conversations(agent_url: str, auth_token: str | None) -> list[dict]:
    response = requests.get(
        f"{_agent_server_http_base_url(agent_url)}/conversations",
        headers=_agent_server_headers(auth_token),
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def _get_conversation(
    agent_url: str, auth_token: str | None, conversation_id: str
) -> dict | None:
    response = requests.get(
        f"{_agent_server_http_base_url(agent_url)}/conversations/{conversation_id}",
        headers=_agent_server_headers(auth_token),
        timeout=10,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else None


def _conversation_messages_to_chat_state(messages: list[dict]) -> tuple[list[Message], list[dict]]:
    ui_messages: list[Message] = []
    agent_messages: list[dict] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "user":
            ui_messages.append(UserMessage(role="user", content=content))
            agent_messages.append({"role": "user", "content": content})
        elif role == "assistant":
            metadata = message.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            artifacts_data = metadata.get("artifacts")
            if isinstance(artifacts_data, dict):
                artifacts = ToolArtifacts(
                    maps=artifacts_data.get("maps", []),
                    thumbnails=artifacts_data.get("thumbnails", []),
                    urls=artifacts_data.get("urls", []),
                )
            else:
                artifacts = ToolArtifacts()
            ui_messages.append(
                AssistantMessage(
                    role="assistant",
                    content=content,
                    artifacts=artifacts,
                    error=bool(metadata.get("error", False)),
                )
            )
            agent_messages.append({"role": "assistant", "content": content})

    return ui_messages, agent_messages


def _load_conversation_into_session(
    agent_url: str, auth_token: str | None, conversation_id: str
) -> None:
    conversation = _get_conversation(agent_url, auth_token, conversation_id)
    if conversation is None:
        st.warning("Conversation not found. Starting a new conversation.")
        st.session_state.conversation_id = None
        st.session_state.loaded_conversation_id = None
        st.session_state.messages = []
        st.session_state.messages_en = []
        st.session_state.pending_location_confirmation = None
        _clear_conversation_id_query_param()
        return

    messages = conversation.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    ui_messages, agent_messages = _conversation_messages_to_chat_state(messages)
    st.session_state.messages = ui_messages
    st.session_state.messages_en = agent_messages
    st.session_state.pending_location_confirmation = None
    st.session_state.loaded_conversation_id = conversation_id


# ---------------------------------------------------
# SESSION VARIABLES (Chat history & agent)
# ---------------------------------------------------
# Type: list[Message] - chat history with user and assistant messages
if "messages" not in st.session_state:
    messages: list[Message] = []
    st.session_state.messages = messages

# Store an English-only chat history for the agent context.
# Type: list[dict] - simple dict format for API calls
if "messages_en" not in st.session_state:
    messages_en: list[dict] = []
    st.session_state.messages_en = messages_en

if "agent_executor" not in st.session_state:
    # Use remote Agent Server via WebSocket
    st.session_state.agent_executor = get_shared_agent_adapter()

if "last_lang" not in st.session_state:
    st.session_state.last_lang = "en"

conversation_id_from_query = _get_conversation_id_from_query_params()

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = conversation_id_from_query
elif conversation_id_from_query != st.session_state.conversation_id:
    st.session_state.conversation_id = conversation_id_from_query
    st.session_state.messages = []
    st.session_state.messages_en = []
    st.session_state.pending_location_confirmation = None
    st.session_state.loaded_conversation_id = None

if "loaded_conversation_id" not in st.session_state:
    st.session_state.loaded_conversation_id = None

if "conversation_titles" not in st.session_state:
    st.session_state.conversation_titles = {}

if "pending_location_confirmation" not in st.session_state:
    st.session_state.pending_location_confirmation = None

if "confirmed_locations" not in st.session_state:
    # Map normalized location_query -> {"token": str, "display": str}
    st.session_state.confirmed_locations = {}

if "auto_confirm_attempts" not in st.session_state:
    # Map normalized location_query -> int attempts in current session
    st.session_state.auto_confirm_attempts = {}

if "document_text" not in st.session_state:
    st.session_state.document_text = ""

if "document_name" not in st.session_state:
    st.session_state.document_name = ""

if "use_document" not in st.session_state:
    st.session_state.use_document = True

agent_executor = st.session_state.agent_executor


# ---------------------------------------------------
# DOCUMENT UPLOAD (PDF) & AGENT MODE
# ---------------------------------------------------
with st.sidebar:
    # Show agent server connection
    st.success("Agent Mode: Remote (Agent Server)")
    agent_url = os.getenv("AGENT_SERVER_URL", "ws://localhost:8080")
    st.caption(f"Connected to: {agent_url}")

    st.subheader("Agent Auth")
    effective_auth_token = ""

    if auth_enabled() and cognito_tokens:
        # Logged in via Cognito Hosted UI: forward the access token.
        claims = cognito_tokens.get("claims") or {}
        user_label = (
            claims.get("email")
            or claims.get("cognito:username")
            or claims.get("username")
            or "Authenticated user"
        )
        st.caption(f"Signed in as: {user_label}")
        effective_auth_token = cognito_tokens.get("access_token") or ""
        render_logout_control()

    if hasattr(agent_executor, "set_auth_token"):
        agent_executor.set_auth_token(effective_auth_token or None)

    if effective_auth_token:
        st.caption("Agent auth token is set.")
    else:
        st.caption("No Agent Server auth token configured.")

    st.divider()
    st.subheader("Conversations")

    if st.button("New conversation", use_container_width=True):
        st.session_state.conversation_id = None
        st.session_state.loaded_conversation_id = None
        st.session_state.messages = []
        st.session_state.messages_en = []
        st.session_state.pending_location_confirmation = None
        _clear_conversation_id_query_param()
        st.rerun()

    try:
        conversations = _list_conversations(agent_url, effective_auth_token or None)
        if not conversations:
            st.caption("No conversations yet.")
        for conversation in conversations:
            conversation_id = str(conversation.get("id") or "")
            if not conversation_id:
                continue
            title = (
                st.session_state.conversation_titles.get(conversation_id)
                or conversation.get("title")
                or "New chat"
            )
            if st.button(
                title,
                key=f"conversation_{conversation_id}",
                use_container_width=True,
            ):
                st.session_state.conversation_id = conversation_id
                st.session_state.loaded_conversation_id = None
                _set_conversation_id_query_param(conversation_id)
                st.rerun()
    except Exception as e:
        logger.warning(f"Failed to load conversations: {type(e).__name__}: {e}")
        st.caption("Could not load conversations.")

    st.divider()
    st.subheader("Document (PDF)")
    uploaded = st.file_uploader(
        "Upload a PDF", type=["pdf"], accept_multiple_files=False
    )
    st.session_state.use_document = st.checkbox(
        "Use document in prompt",
        value=bool(st.session_state.use_document),
    )

    if uploaded is not None:
        try:
            logger.info(f"Processing uploaded PDF: {uploaded.name}")
            pdf_bytes = uploaded.getvalue()
            # Hard cap: avoid gigantic uploads impacting memory/prompt.
            if (
                isinstance(pdf_bytes, (bytes, bytearray))
                and len(pdf_bytes) > 10 * 1024 * 1024
            ):
                logger.warning(f"PDF too large: {len(pdf_bytes)} bytes (max 10MB)")
                st.error("PDF too large (max 10MB).")
            else:
                text = extract_text_from_pdf_bytes(pdf_bytes, max_chars=120_000)
                st.session_state.document_text = text
                st.session_state.document_name = uploaded.name or ""
                if text:
                    logger.info(f"PDF loaded successfully: {len(text)} chars extracted")
                    st.caption(f"Loaded {uploaded.name} ({len(text)} chars extracted)")
                else:
                    logger.warning("No extractable text found in PDF")
                    st.warning("No extractable text found in this PDF.")
        except Exception as e:
            logger.error(
                f"PDF extraction failed: {type(e).__name__}: {str(e)}", exc_info=True
            )
            st.error(f"PDF extraction failed: {e}")

    if st.session_state.document_text:
        with st.expander("Preview extracted text"):
            st.text(st.session_state.document_text[:4000])

    if st.button("Clear document"):
        logger.info("Clearing document context")
        st.session_state.document_text = ""
        st.session_state.document_name = ""


if (
    st.session_state.conversation_id
    and st.session_state.loaded_conversation_id != st.session_state.conversation_id
):
    try:
        _load_conversation_into_session(
            agent_url,
            effective_auth_token or None,
            st.session_state.conversation_id,
        )
    except Exception as e:
        logger.warning(
            f"Failed to load conversation {st.session_state.conversation_id}: {type(e).__name__}: {e}"
        )
        st.warning("Could not load the selected conversation.")


# ---------------------------------------------------
# DISPLAY CHAT HISTORY
# ---------------------------------------------------
for msg in st.session_state.messages:
    role = msg["role"]
    content = msg["content"]

    # Extract artifacts for assistant messages using type narrowing
    artifacts = ToolArtifacts()
    is_error = False
    maps: list = []
    thumbnails: list = []
    stored_tool_calls: list[ToolCallRecord] = []

    if role == "assistant":
        # Type narrowing: msg is AssistantMessage here
        assistant_msg: AssistantMessage = msg  # type: ignore
        artifacts = assistant_msg["artifacts"]
        is_error = assistant_msg["error"]
        maps = artifacts.maps if hasattr(artifacts, "maps") else []
        thumbnails = artifacts.thumbnails if hasattr(artifacts, "thumbnails") else []
        stored_tool_calls = assistant_msg.get("tool_calls") or []

    with st.chat_message(role):
        if role == "assistant" and stored_tool_calls:
            _render_tool_status_box(
                [_record_to_tool_call(record) for record in stored_tool_calls]
            )
        if role == "assistant" and is_error:
            st.error(content or "An error occurred.")
        elif role != "assistant":
            st.write(content)
        else:
            # assistant + not error
            # Show map if any item is a legacy HTML path or a spec with view_state
            # (view_state alone is enough to show a basemap centered on the location)
            has_map = any(
                (isinstance(x, str) and x.endswith(".html"))
                or (
                    isinstance(x, dict)
                    and isinstance(x.get("view_state"), dict)
                )
                for x in maps
            )

            def _is_displayable_image_url(url: str) -> bool:
                """True if the URL points to an image format browsers can display (not COG/GeoTIFF)."""
                u = url.lower().split("?")[0]
                return u.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))

            def _is_cog_url(url: str) -> bool:
                """True if the URL is likely a Cloud-Optimized GeoTIFF we can preview."""
                u = url.lower().split("?")[0]
                return u.endswith(".tif") or u.endswith(".tiff")

            def _render_thumbnail_or_link(url: str) -> None:
                if not url.startswith("http://") and not url.startswith("https://"):
                    st.caption(f"Image: {url}")
                    return
                if _is_displayable_image_url(url):
                    st.image(url, width=300)
                elif _is_cog_url(url):
                    png_bytes = _cog_url_to_png_bytes(url)
                    if png_bytes:
                        st.image(png_bytes, width=300)
                        st.caption("Preview (COG). [Open full COG in viewer](%s)" % url)
                    else:
                        st.markdown(f"[Open image/COG in viewer]({url})")
                        st.caption("GeoTIFF/COG — open in QGIS or a COG-capable viewer.")
                else:
                    st.markdown(f"[Open image/COG in viewer]({url})")
                    st.caption("GeoTIFF/COG — open in QGIS or a COG-capable viewer.")

            if has_map:
                col_text, col_map = st.columns([2, 3], vertical_alignment="top")
                with col_text:
                    st.write(content)

                with col_map:
                    for item in maps:
                        if isinstance(item, dict) and isinstance(
                            item.get("view_state"), dict
                        ):
                            _render_pydeck_map_spec(item)

                    if thumbnails:
                        st.write("### Satellite Images:")
                        for url in thumbnails:
                            if isinstance(url, str) and url:
                                _render_thumbnail_or_link(url)
            else:
                st.write(content)
                if thumbnails:
                    st.write("### Satellite Images:")
                    for url in thumbnails:
                        if isinstance(url, str) and url:
                            _render_thumbnail_or_link(url)


# ---------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------
pending = st.session_state.pending_location_confirmation
if isinstance(pending, dict) and pending.get("candidates"):
    st.info("Please confirm the intended location to continue.")
    location_query = (
        pending.get("location_query")
        if isinstance(pending.get("location_query"), str)
        else None
    )
    norm_key = (
        " ".join(location_query.lower().split())
        if isinstance(location_query, str)
        else None
    )

    # If we've already confirmed this exact ambiguous query earlier in the session,
    # auto-apply the same choice to avoid asking repeatedly (common when multiple
    # tools need the same city).
    cached = st.session_state.confirmed_locations.get(norm_key) if norm_key else None
    attempts = (
        st.session_state.auto_confirm_attempts.get(norm_key, 0) if norm_key else 0
    )
    if (
        isinstance(cached, dict)
        and isinstance(cached.get("token"), str)
        and norm_key
        and attempts < 1
    ):
        patched_value = cached.get("token") if cached else None

        st.session_state.auto_confirm_attempts[norm_key] = attempts + 1
        st.session_state.pending_location_confirmation = None

        with st.chat_message("assistant"):
            tools_placeholder = st.empty()
            trace_placeholder = st.empty()
            message_placeholder = st.empty()
            tools_callback, trace_callback, tool_snapshot = _make_streaming_event_handler(
                tools_placeholder=tools_placeholder,
                trace_placeholder=trace_placeholder,
            )
            try:
                logger.debug(
                    f"Auto-confirming location, resuming conversation_id={st.session_state.conversation_id}"
                )
                auto_loc = _confirmed_location_from_cache(
                    cached.get("display", ""), patched_value
                )
                result = _invoke_agent_with_streaming_display(
                    agent_executor,
                    message_placeholder=message_placeholder,
                    tools_callback=tools_callback,
                    trace_callback=trace_callback,
                    english_query="",
                    resume=True,
                    confirmed_location=auto_loc,
                    conversation_id=st.session_state.conversation_id,
                )
                tool_calls = tool_snapshot()
                _store_conversation_id(result.conversation_id)
                _store_conversation_title(
                    result.conversation_id, result.conversation_title
                )
                logger.info("Auto-confirm completed successfully")
                logger.debug(
                    f"Result: error={result.error}, needs_confirmation={result.needs_location_confirmation}"
                )

                # Check if location confirmation is needed
                if result.needs_location_confirmation:
                    logger.info("Another location confirmation needed")
                    st.session_state.pending_location_confirmation = {
                        "needs_location_confirmation": True,
                        "candidates": result.location_options,
                        "pause": result.pause_state,
                    }

                detected_lang = st.session_state.last_lang or "en"
                assistant_message_en = result.message or ""
                if not isinstance(assistant_message_en, str):
                    assistant_message_en = str(assistant_message_en)

                ui_message = assistant_message_en
                if isinstance(ui_message, str):
                    ui_message = translate_from_english(ui_message, detected_lang)
                message_placeholder.markdown(ui_message)

                st.session_state.messages_en.append(
                    {"role": "assistant", "content": assistant_message_en}
                )
                st.session_state.messages.append(
                    AssistantMessage(
                        role="assistant",
                        content=ui_message,
                        artifacts=result.artifacts,
                        error=result.error,
                        tool_calls=tool_calls,
                    )
                )
            except Exception as e:
                logger.error(
                    f"Error during auto-confirm: {type(e).__name__}: {str(e)}",
                    exc_info=True,
                )
                error_msg = f"❌ Error: {str(e)}"
                message_placeholder.error(error_msg)
                st.session_state.messages.append(
                    AssistantMessage(
                        role="assistant",
                        content=error_msg,
                        artifacts=ToolArtifacts(),
                        error=True,
                        tool_calls=tool_snapshot(),
                    )
                )
                st.session_state.messages_en.append(
                    {"role": "assistant", "content": error_msg}
                )
            finally:
                trace_placeholder.empty()

        st.rerun()

    candidates: list[LocationOption] = [
        LocationOption(
            name=c.name,
            coordinates=c.coordinates,
            place_id=c.place_id,
            osm_id=c.osm_id,
            osm_type=c.osm_type,
            osm_type_prefix=c.osm_type_prefix,
        )
        for c in pending.get("candidates") or []
    ]

    def _candidate_label(candidate: LocationOption) -> str:
        display = str(candidate.name)
        lat = candidate.coordinates[0]
        lon = candidate.coordinates[1]
        place_id = candidate.place_id
        return f"{display} ({float(lat):.4f}, {float(lon):.4f}) place_id={place_id}"

    with st.form("location_confirmation_form"):
        choice = st.selectbox(
            "Select a location",
            options=candidates,
            format_func=_candidate_label,
        )
        submitted = st.form_submit_button("Confirm location")

    if submitted:
        logger.info(f"User confirmed location choice: {choice.name}")

        patched_value = None
        chosen_display = choice.name
        if choice.osm_id is not None and choice.osm_type is not None:
            prefix = get_osm_type_prefix(choice.osm_type)
            patched_value = f"@osm_id:{prefix}{choice.osm_id}"
        elif choice.place_id is not None:
            patched_value = f"@place_id:{choice.place_id}"
        else:
            logger.warning("No OSM ID or place ID found for chosen location")
            patched_value = chosen_display or ""

        # The paused agent state lives server-side; the client only references the
        # conversation id when resuming. Local cache below is a UX optimization.

        # Cache confirmation for this query so other tools can reuse it.
        if norm_key:
            # Store under both the full query and its base token (before comma)
            # to handle cases like "Paris" vs "Paris, France".
            base_key = (
                norm_key.split(",", 1)[0].strip() if "," in norm_key else norm_key
            )
            for k in {norm_key, base_key}:
                if k:
                    st.session_state.confirmed_locations[k] = {
                        "token": patched_value,
                        "display": chosen_display or "",
                    }
            # Reset auto-confirm attempts after an explicit choice.
            st.session_state.auto_confirm_attempts[norm_key] = 0
            if base_key != norm_key:
                st.session_state.auto_confirm_attempts[base_key] = 0

        # Append a short confirmation message to chat history for user visibility.
        detected_lang = st.session_state.last_lang or "en"
        confirm_en = f"Confirmed location: {chosen_display or patched_value}"
        confirm_ui = (
            translate_from_english(confirm_en, detected_lang)
            if detected_lang != "en"
            else confirm_en
        )
        st.session_state.messages.append(UserMessage(role="user", content=confirm_ui))
        st.session_state.messages_en.append({"role": "user", "content": confirm_en})

        # Clear pending state before resuming.
        st.session_state.pending_location_confirmation = None

        with st.chat_message("assistant"):
            tools_placeholder = st.empty()
            trace_placeholder = st.empty()
            message_placeholder = st.empty()
            tools_callback, trace_callback, tool_snapshot = _make_streaming_event_handler(
                tools_placeholder=tools_placeholder,
                trace_placeholder=trace_placeholder,
            )
            try:
                logger.debug(
                    f"Resuming after location confirmation: conversation_id={st.session_state.conversation_id}"
                )
                logger.debug(f"Patched value: {patched_value}")
                confirmed_loc = {
                    "name": choice.name,
                    "coordinates": choice.coordinates,
                    "place_id": choice.place_id,
                    "osm_id": choice.osm_id,
                    "osm_type": choice.osm_type,
                    "osm_type_prefix": choice.osm_type_prefix,
                }
                result = _invoke_agent_with_streaming_display(
                    agent_executor,
                    message_placeholder=message_placeholder,
                    tools_callback=tools_callback,
                    trace_callback=trace_callback,
                    english_query="",
                    resume=True,
                    confirmed_location=confirmed_loc,
                    conversation_id=st.session_state.conversation_id,
                )
                tool_calls = tool_snapshot()
                _store_conversation_id(result.conversation_id)
                _store_conversation_title(
                    result.conversation_id, result.conversation_title
                )
                logger.info(
                    "Resume after location confirmation completed successfully"
                )
                logger.debug(
                    f"Result: error={result.error}, needs_confirmation={result.needs_location_confirmation}"
                )

                # Check if location confirmation is needed
                if result.needs_location_confirmation:
                    logger.info("Another location confirmation needed")
                    st.session_state.pending_location_confirmation = {
                        "needs_location_confirmation": True,
                        "candidates": result.location_options,
                        "pause": result.pause_state,
                    }

                assistant_message_en = result.message or ""
                if not isinstance(assistant_message_en, str):
                    assistant_message_en = str(assistant_message_en)

                ui_message = assistant_message_en
                if isinstance(ui_message, str):
                    ui_message = translate_from_english(ui_message, detected_lang)
                message_placeholder.markdown(ui_message)

                st.session_state.messages_en.append(
                    {"role": "assistant", "content": assistant_message_en}
                )
                st.session_state.messages.append(
                    AssistantMessage(
                        role="assistant",
                        content=ui_message,
                        artifacts=result.artifacts,
                        error=result.error,
                        tool_calls=tool_calls,
                    )
                )
            except Exception as e:
                logger.error(
                    f"Error during resume: {type(e).__name__}: {str(e)}",
                    exc_info=True,
                )
                error_msg = f"❌ Error: {str(e)}"
                message_placeholder.error(error_msg)
                st.session_state.messages.append(
                    AssistantMessage(
                        role="assistant",
                        content=error_msg,
                        artifacts=ToolArtifacts(),
                        error=True,
                        tool_calls=tool_snapshot(),
                    )
                )
                st.session_state.messages_en.append(
                    {"role": "assistant", "content": error_msg}
                )
            finally:
                trace_placeholder.empty()

        st.rerun()

# Normal chat input path (disabled while waiting for confirmation)
user_input = st.chat_input(
    "Ask me anything about Earth observation or STAC...",
    disabled=bool(st.session_state.pending_location_confirmation),
)

if user_input:
    logger.info(f"New user input received: {user_input[:100]}...")
    st.session_state.messages.append(UserMessage(role="user", content=user_input))
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        tools_placeholder = st.empty()
        trace_placeholder = st.empty()
        message_placeholder = st.empty()
        tools_callback, trace_callback, tool_snapshot = _make_streaming_event_handler(
            tools_placeholder=tools_placeholder,
            trace_placeholder=trace_placeholder,
        )

        try:
            english_query, detected_lang = detect_and_translate_to_english(
                user_input
            )
            st.session_state.last_lang = detected_lang
            st.session_state.messages_en.append(
                {"role": "user", "content": english_query}
            )

            english_query_augmented = _augment_with_document(english_query)
            logger.debug(
                f"Invoking agent with query: {english_query_augmented[:100]}..."
            )
            history_for_agent = st.session_state.messages_en[:-1]
            result = _invoke_agent_with_streaming_display(
                agent_executor,
                message_placeholder=message_placeholder,
                tools_callback=tools_callback,
                trace_callback=trace_callback,
                english_query=english_query_augmented,
                conversation_id=st.session_state.conversation_id,
                chat_history=history_for_agent,
            )
            tool_calls = tool_snapshot()
            _store_conversation_id(result.conversation_id)
            _store_conversation_title(
                result.conversation_id, result.conversation_title
            )
            logger.info("Agent response received successfully")
            logger.debug(
                f"Result: error={result.error}, needs_confirmation={result.needs_location_confirmation}"
            )

            # Check if location confirmation is needed
            if result.needs_location_confirmation:
                logger.info("Location confirmation required")

                st.session_state.pending_location_confirmation = {
                    "needs_location_confirmation": True,
                    "candidates": result.location_options,
                    "pause": result.pause_state,
                }

            assistant_message_en = result.message or ""
            if not isinstance(assistant_message_en, str):
                assistant_message_en = str(assistant_message_en)

            ui_message = assistant_message_en
            if isinstance(ui_message, str):
                ui_message = translate_from_english(ui_message, detected_lang)
            message_placeholder.markdown(ui_message)

            st.session_state.messages_en.append(
                {"role": "assistant", "content": assistant_message_en}
            )
            st.session_state.messages.append(
                AssistantMessage(
                    role="assistant",
                    content=ui_message,
                    artifacts=result.artifacts,
                    error=result.error,
                    tool_calls=tool_calls,
                )
            )

        except Exception as e:
            logger.error(
                f"Error during chat: {type(e).__name__}: {str(e)}"
            )
            error_msg = f"Error: {str(e)}"
            message_placeholder.error(error_msg)
            st.session_state.messages.append(
                AssistantMessage(
                    role="assistant",
                    content=error_msg,
                    artifacts=ToolArtifacts(),
                    error=True,
                    tool_calls=tool_snapshot(),
                )
            )
            st.session_state.messages_en.append(
                {"role": "assistant", "content": error_msg}
            )

        finally:
            trace_placeholder.empty()

    st.rerun()
