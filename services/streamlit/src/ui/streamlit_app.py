"""Streamlit UI for MetaplanetLLM.

Renders assistant responses, including map artifacts (HTML or Pydeck specs).
"""

import io
import os
import sys
from pathlib import Path
from typing import Literal
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
class UserMessage(TypedDict):
    """User message in chat history."""

    role: Literal["user"]
    content: str


class AssistantMessage(TypedDict):
    """Assistant message in chat history."""

    role: Literal["assistant"]
    content: str
    artifacts: ToolArtifacts
    error: bool


# Union type for all message types
Message = UserMessage | AssistantMessage


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

        if et == "data_agent_step":
            phase = evt.get("phase")
            tool_name = evt.get("tool_name")
            commentary = evt.get("commentary")
            tool_input = evt.get("tool_input")
            observation = evt.get("observation")
            error = bool(evt.get("error"))

            if isinstance(commentary, str) and commentary.strip():
                push(commentary)
            if isinstance(tool_name, str) and tool_name.strip():
                push(f"Action: {tool_name} ({'error' if error else phase})")
            if tool_input is not None and phase in {"planned", "running"}:
                push(f"Input: {_shorten(str(tool_input), max_len=180)}")
            if observation is not None and phase == "done":
                push(f"Observation: {_shorten(str(observation), max_len=220)}")
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
            ui_messages.append(
                AssistantMessage(
                    role="assistant",
                    content=content,
                    artifacts=ToolArtifacts(),
                    error=False,
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

    if role == "assistant":
        # Type narrowing: msg is AssistantMessage here
        assistant_msg: AssistantMessage = msg  # type: ignore
        artifacts = assistant_msg["artifacts"]
        is_error = assistant_msg["error"]
        maps = artifacts.maps if hasattr(artifacts, "maps") else []
        thumbnails = artifacts.thumbnails if hasattr(artifacts, "thumbnails") else []

    with st.chat_message(role):
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
        pause_value = pending.get("pause")
        resume = pause_value if isinstance(pause_value, dict) else {}
        resume_state_value = resume.get("resume_state")
        resume_state = (
            resume_state_value if isinstance(resume_state_value, dict) else None
        )
        resume_patch_value = pending.get("resume_patch")
        resume_patch = (
            resume_patch_value if isinstance(resume_patch_value, dict) else {}
        )
        field = resume_patch.get("field") if resume_patch else None
        patched_value = cached.get("token") if cached else None

        if isinstance(resume_state, dict):
            next_input = resume_state.get("next_input")
            if isinstance(field, str) and field.strip():
                if isinstance(next_input, dict):
                    next_input[field] = patched_value
                else:
                    resume_state["next_input"] = {field: patched_value}
            else:
                resume_state["next_input"] = patched_value

            confirmed = resume_state.get("confirmed_locations")
            if not isinstance(confirmed, dict):
                confirmed = {}
            confirmed[norm_key] = patched_value
            resume_state["confirmed_locations"] = confirmed
            resume["resume_state"] = resume_state

        st.session_state.auto_confirm_attempts[norm_key] = attempts + 1
        st.session_state.pending_location_confirmation = None

        with st.chat_message("assistant"):
            with st.spinner("Continuing..."):
                trace_placeholder = st.empty()
                live_callback = _make_live_trace_updater(trace_placeholder)
                try:
                    english_query = resume.get("user_text") or ""
                    english_query_augmented = _augment_with_document(english_query)
                    logger.debug(
                        f"Auto-confirming location, resuming with query: {english_query_augmented[:100]}..."
                    )
                    history_for_agent = st.session_state.messages_en
                    auto_loc = {
                        "name": cached.get("display", ""),
                        "coordinates": [0, 0],
                    }
                    result = _invoke_agent_unified(
                        agent_executor,
                        english_query_augmented,
                        chat_history=history_for_agent,
                        resume=resume,
                        confirmed_location=auto_loc,
                        stream_callback=live_callback,
                    )
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

                    st.session_state.messages_en.append(
                        {"role": "assistant", "content": assistant_message_en}
                    )
                    st.session_state.messages.append(
                        AssistantMessage(
                            role="assistant",
                            content=ui_message,
                            artifacts=result.artifacts,
                            error=result.error,
                        )
                    )
                except Exception as e:
                    error_msg = f"❌ Error: {str(e)}"
                    st.session_state.messages.append(
                        AssistantMessage(
                            role="assistant",
                            content=error_msg,
                            artifacts=ToolArtifacts(),
                            error=True,
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

        pause_value = pending.get("pause")
        resume = pause_value if isinstance(pause_value, dict) else {}
        resume_state_value = resume.get("resume_state")
        resume_state = (
            resume_state_value if isinstance(resume_state_value, dict) else None
        )
        resume_patch_value = pending.get("resume_patch")
        resume_patch = (
            resume_patch_value if isinstance(resume_patch_value, dict) else {}
        )
        field = resume_patch.get("field") if resume_patch else None

        # Prefer a stable token that resolves to the exact chosen place.

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

        if isinstance(resume_state, dict):
            next_input = resume_state.get("next_input")
            if isinstance(field, str) and field.strip():
                if isinstance(next_input, dict):
                    next_input[field] = patched_value
                else:
                    resume_state["next_input"] = {field: patched_value}
            else:
                # Fallback: replace next_input entirely.
                resume_state["next_input"] = patched_value

            # Persist confirmed disambiguations into the agent state so later planner
            # steps can reuse them (avoid re-asking for the same city).
            if norm_key:
                confirmed = resume_state.get("confirmed_locations")
                if not isinstance(confirmed, dict):
                    confirmed = {}
                confirmed[norm_key] = patched_value
                base_key = (
                    norm_key.split(",", 1)[0].strip() if "," in norm_key else norm_key
                )
                if base_key and base_key != norm_key:
                    confirmed[base_key] = patched_value
                resume_state["confirmed_locations"] = confirmed

            resume["resume_state"] = resume_state

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
            with st.spinner("Continuing..."):
                trace_placeholder = st.empty()
                live_callback = _make_live_trace_updater(trace_placeholder)
                try:
                    english_query = resume.get("user_text") or ""
                    english_query_augmented = _augment_with_document(english_query)
                    logger.debug(
                        f"Resuming after location confirmation: {english_query_augmented[:100]}..."
                    )
                    logger.debug(f"Resume state: {resume_state}")
                    logger.debug(f"Resume patch: {resume_patch}")
                    logger.debug(f"Field: {field}")
                    logger.debug(f"Patched value: {patched_value}")
                    history_for_agent = st.session_state.messages_en[:-1]
                    confirmed_loc = {
                        "name": choice.name,
                        "coordinates": choice.coordinates,
                        "place_id": choice.place_id,
                        "osm_id": choice.osm_id,
                        "osm_type": choice.osm_type,
                        "osm_type_prefix": choice.osm_type_prefix,
                    }
                    result = _invoke_agent_unified(
                        agent_executor,
                        english_query_augmented,
                        chat_history=history_for_agent,
                        resume=resume,
                        confirmed_location=confirmed_loc,
                        stream_callback=live_callback,
                    )
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

                    st.session_state.messages_en.append(
                        {"role": "assistant", "content": assistant_message_en}
                    )
                    st.session_state.messages.append(
                        AssistantMessage(
                            role="assistant",
                            content=ui_message,
                            artifacts=result.artifacts,
                            error=result.error,
                        )
                    )
                except Exception as e:
                    logger.error(
                        f"Error during resume: {type(e).__name__}: {str(e)}",
                        exc_info=True,
                    )
                    error_msg = f"❌ Error: {str(e)}"
                    st.session_state.messages.append(
                        AssistantMessage(
                            role="assistant",
                            content=error_msg,
                            artifacts=ToolArtifacts(),
                            error=True,
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
        with st.spinner("Thinking..."):
            trace_placeholder = st.empty()
            live_callback = _make_live_trace_updater(trace_placeholder)

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
                result = _invoke_agent_unified(
                    agent_executor,
                    english_query_augmented,
                    conversation_id=st.session_state.conversation_id,
                    chat_history=history_for_agent,
                    stream_callback=live_callback,
                )
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

                st.session_state.messages_en.append(
                    {"role": "assistant", "content": assistant_message_en}
                )
                st.session_state.messages.append(
                    AssistantMessage(
                        role="assistant",
                        content=ui_message,
                        artifacts=result.artifacts,
                        error=result.error,
                    )
                )

            except Exception as e:
                logger.error(
                    f"Error during chat: {type(e).__name__}: {str(e)}"
                )
                error_msg = f"Error: {str(e)}"
                st.session_state.messages.append(
                    AssistantMessage(
                        role="assistant",
                        content=error_msg,
                        artifacts=ToolArtifacts(),
                        error=True,
                    )
                )
                st.session_state.messages_en.append(
                    {"role": "assistant", "content": error_msg}
                )

            finally:
                trace_placeholder.empty()

    st.rerun()
