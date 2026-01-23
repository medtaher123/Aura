"""Streamlit UI for MetaplanetLLM.

Renders assistant responses, including map artifacts (HTML or Pydeck specs).
"""

import sys
import os
from pathlib import Path

import streamlit as st
import pydeck as pdk
from PIL import Image
from dotenv import load_dotenv

# Ensure project root is on sys.path so absolute imports work when running via
# `streamlit run src/ui/streamlit_app.py`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load local env vars (e.g., MAPTILER_API_KEY) from repo `.env`.
load_dotenv(PROJECT_ROOT / ".env", override=False)

from src.services.agent_runner import invoke_agent, coerce_tool_response
from src.tools import make_tool_response
from src.services.document_service import extract_text_from_pdf_bytes

MAPS_DIR = PROJECT_ROOT / "src" / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

from src.services.orchestrator_agent_service import create_orchestrator_executor
from src.services import detect_and_translate_to_english, translate_from_english


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
        tooltip=tooltip,
    )
    st.pydeck_chart(deck, use_container_width=True, height=item.get("height", 450))


def _shorten(text: str, *, max_len: int = 220) -> str:
    if not isinstance(text, str):
        text = str(text)
    s = " ".join(text.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _make_live_trace_updater(trace_placeholder: st.delta_generator.DeltaGenerator):
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
            for l in tail:
                st.caption(l)

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


# ---------------------------------------------------
# SESSION VARIABLES (Chat history & agent)
# ---------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# Store an English-only chat history for the agent context.
if "messages_en" not in st.session_state:
    st.session_state.messages_en = []

if "agent_executor" not in st.session_state:
    st.session_state.agent_executor = create_orchestrator_executor()

if "last_lang" not in st.session_state:
    st.session_state.last_lang = "en"

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
# DOCUMENT UPLOAD (PDF)
# ---------------------------------------------------
with st.sidebar:
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
            pdf_bytes = uploaded.getvalue()
            # Hard cap: avoid gigantic uploads impacting memory/prompt.
            if (
                isinstance(pdf_bytes, (bytes, bytearray))
                and len(pdf_bytes) > 10 * 1024 * 1024
            ):
                st.error("PDF too large (max 10MB).")
            else:
                text = extract_text_from_pdf_bytes(pdf_bytes, max_chars=120_000)
                st.session_state.document_text = text
                st.session_state.document_name = uploaded.name or ""
                if text:
                    st.caption(f"Loaded {uploaded.name} ({len(text)} chars extracted)")
                else:
                    st.warning("No extractable text found in this PDF.")
        except Exception as e:
            st.error(f"PDF extraction failed: {e}")

    if st.session_state.document_text:
        with st.expander("Preview extracted text"):
            st.text(st.session_state.document_text[:4000])

    if st.button("Clear document"):
        st.session_state.document_text = ""
        st.session_state.document_name = ""


# ---------------------------------------------------
# DISPLAY CHAT HISTORY
# ---------------------------------------------------
for msg in st.session_state.messages:
    role = msg.get("role", "assistant")
    content = msg.get("content", "")
    artifacts = msg.get("artifacts") or {}
    maps = artifacts.get("maps") or []
    thumbnails = artifacts.get("thumbnails") or []
    is_error = bool(msg.get("error"))

    with st.chat_message(role):
        if role == "assistant" and is_error:
            st.error(content or "An error occurred.")
        elif role != "assistant":
            st.write(content)
        else:
            # assistant + not error
            has_map = any(
                (isinstance(x, str) and x.endswith(".html"))
                or (
                    isinstance(x, dict)
                    and isinstance(x.get("view_state"), dict)
                    and (
                        isinstance(x.get("points"), list)
                        or isinstance(x.get("layers"), list)
                    )
                )
                for x in maps
            )

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
                                st.image(url, width=300)
            else:
                st.write(content)
                if thumbnails:
                    st.write("### Satellite Images:")
                    for url in thumbnails:
                        if isinstance(url, str) and url:
                            st.image(url, width=300)


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
        resume = pending.get("pause") if isinstance(pending.get("pause"), dict) else {}
        resume_state = (
            resume.get("resume_state")
            if isinstance(resume.get("resume_state"), dict)
            else None
        )
        resume_patch = (
            pending.get("resume_patch")
            if isinstance(pending.get("resume_patch"), dict)
            else {}
        )
        field = resume_patch.get("field")
        patched_value = cached.get("token")

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
                    english_query = _augment_with_document(english_query)
                    print("english_query:", english_query)
                    history_for_agent = st.session_state.messages_en
                    agent_output = invoke_agent(
                        agent_executor,
                        english_query,
                        chat_history=history_for_agent,
                        resume=resume,
                        stream_callback=live_callback,
                    )

                    result = coerce_tool_response(agent_output)
                    print("Auto-confirm result:", result)
                    if not isinstance(result, dict):
                        result = make_tool_response(
                            tool_name="ui",
                            message=str(result),
                            artifacts={"maps": [], "thumbnails": [], "urls": []},
                            error=True,
                        )

                    data = (
                        result.get("data")
                        if isinstance(result.get("data"), dict)
                        else {}
                    )
                    if bool(data.get("needs_location_confirmation")) is True:
                        st.session_state.pending_location_confirmation = data

                    detected_lang = st.session_state.last_lang or "en"
                    assistant_message_en = result.get("message") or ""
                    if not isinstance(assistant_message_en, str):
                        assistant_message_en = str(assistant_message_en)

                    ui_message = result.get("message") or ""
                    if isinstance(ui_message, str):
                        ui_message = translate_from_english(ui_message, detected_lang)

                    st.session_state.messages_en.append(
                        {"role": "assistant", "content": assistant_message_en}
                    )
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": ui_message,
                            "artifacts": (result.get("artifacts") or {}),
                            "error": bool(result.get("error")),
                        }
                    )
                except Exception as e:
                    error_msg = f"❌ Error: {str(e)}"
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": error_msg,
                            "artifacts": {},
                            "error": True,
                        }
                    )
                    st.session_state.messages_en.append(
                        {"role": "assistant", "content": error_msg}
                    )
                finally:
                    trace_placeholder.empty()

        st.rerun()

    candidates = pending.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    def _candidate_label(c: dict) -> str:
        display = str(c.get("display_name") or c.get("name") or "(unknown)")
        lat = c.get("lat")
        lon = c.get("lon")
        pid = c.get("place_id")
        suffix_parts: list[str] = []
        try:
            if lat is not None and lon is not None:
                suffix_parts.append(f"{float(lat):.4f}, {float(lon):.4f}")
        except Exception:
            pass
        if pid is not None:
            suffix_parts.append(f"place_id={pid}")
        if suffix_parts:
            return f"{display} ({' | '.join(suffix_parts)})"
        return display

    option_indices = list(range(len(candidates)))

    with st.form("location_confirmation_form"):
        choice_idx = st.radio(
            "Select a location",
            options=option_indices,
            index=0,
            format_func=lambda i: _candidate_label(candidates[i])
            if 0 <= i < len(candidates) and isinstance(candidates[i], dict)
            else str(i),
        )
        submitted = st.form_submit_button("Confirm location")

    if submitted:
        chosen = (
            candidates[choice_idx]
            if isinstance(choice_idx, int) and 0 <= choice_idx < len(candidates)
            else None
        )
        chosen_display = None
        chosen_token = None
        if isinstance(chosen, dict):
            chosen_display = str(chosen.get("display_name") or chosen.get("name") or "")
            osm_type = chosen.get("osm_type")
            osm_id = chosen.get("osm_id")
            if osm_type in {"relation", "way", "node"} and osm_id is not None:
                prefix = {"relation": "R", "way": "W", "node": "N"}.get(osm_type)
                if prefix:
                    chosen_token = f"@osm_id:{prefix}{int(osm_id)}"
            if not chosen_token:
                pid = chosen.get("place_id")
                if pid is not None:
                    chosen_token = f"@place_id:{pid}"

        resume = pending.get("pause") if isinstance(pending.get("pause"), dict) else {}
        resume_state = (
            resume.get("resume_state")
            if isinstance(resume.get("resume_state"), dict)
            else None
        )
        resume_patch = (
            pending.get("resume_patch")
            if isinstance(pending.get("resume_patch"), dict)
            else {}
        )
        field = resume_patch.get("field")

        # Prefer a stable token that resolves to the exact chosen place.
        patched_value = chosen_token or chosen_display or ""

        # Cache confirmation for this query so other tools can reuse it.
        if norm_key:
            display_val = chosen_display or patched_value
            # Store under both the full query and its base token (before comma)
            # to handle cases like "Paris" vs "Paris, France".
            base_key = (
                norm_key.split(",", 1)[0].strip() if "," in norm_key else norm_key
            )
            for k in {norm_key, base_key}:
                if k:
                    st.session_state.confirmed_locations[k] = {
                        "token": patched_value,
                        "display": display_val,
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
        st.session_state.messages.append({"role": "user", "content": confirm_ui})
        st.session_state.messages_en.append({"role": "user", "content": confirm_en})

        # Clear pending state before resuming.
        st.session_state.pending_location_confirmation = None

        with st.chat_message("assistant"):
            with st.spinner("Continuing..."):
                trace_placeholder = st.empty()
                live_callback = _make_live_trace_updater(trace_placeholder)
                try:
                    english_query = resume.get("user_text") or ""
                    english_query = _augment_with_document(english_query)
                    print("english_query:", english_query)
                    history_for_agent = st.session_state.messages_en[:-1]
                    agent_output = invoke_agent(
                        agent_executor,
                        english_query,
                        chat_history=history_for_agent,
                        resume=resume,
                        stream_callback=live_callback,
                    )

                    result = coerce_tool_response(agent_output)
                    print("Auto-confirm result in coerce_tool_response:", result)
                    if not isinstance(result, dict):
                        result = make_tool_response(
                            tool_name="ui",
                            message=str(result),
                            artifacts={"maps": [], "thumbnails": [], "urls": []},
                            error=True,
                        )

                    # If we paused again, store pending and show the prompt.
                    data = (
                        result.get("data")
                        if isinstance(result.get("data"), dict)
                        else {}
                    )
                    if bool(data.get("needs_location_confirmation")) is True:
                        st.session_state.pending_location_confirmation = data

                    assistant_message_en = result.get("message") or ""
                    if not isinstance(assistant_message_en, str):
                        assistant_message_en = str(assistant_message_en)

                    ui_message = result.get("message") or ""
                    if isinstance(ui_message, str):
                        ui_message = translate_from_english(ui_message, detected_lang)

                    st.session_state.messages_en.append(
                        {"role": "assistant", "content": assistant_message_en}
                    )
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": ui_message,
                            "artifacts": (result.get("artifacts") or {}),
                            "error": bool(result.get("error")),
                        }
                    )
                except Exception as e:
                    error_msg = f"❌ Error: {str(e)}"
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": error_msg,
                            "artifacts": {},
                            "error": True,
                        }
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
    st.session_state.messages.append({"role": "user", "content": user_input})
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

                english_query = _augment_with_document(english_query)
                print("english_query:", english_query)
                history_for_agent = st.session_state.messages_en[:-1]
                agent_output = invoke_agent(
                    agent_executor,
                    english_query,
                    chat_history=history_for_agent,
                    stream_callback=live_callback,
                )

                result = coerce_tool_response(agent_output)
                print("Auto-confirm result 3:", result)
                if not isinstance(result, dict):
                    result = make_tool_response(
                        tool_name="ui",
                        message=str(result),
                        artifacts={"maps": [], "thumbnails": [], "urls": []},
                        error=True,
                    )

                data = (
                    result.get("data") if isinstance(result.get("data"), dict) else {}
                )
                if bool(data.get("needs_location_confirmation")) is True:
                    st.session_state.pending_location_confirmation = data

                assistant_message_en = result.get("message") or ""
                if not isinstance(assistant_message_en, str):
                    assistant_message_en = str(assistant_message_en)

                ui_message = result.get("message") or ""
                if isinstance(ui_message, str):
                    ui_message = translate_from_english(ui_message, detected_lang)

                st.session_state.messages_en.append(
                    {"role": "assistant", "content": assistant_message_en}
                )
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": ui_message,
                        "artifacts": (result.get("artifacts") or {}),
                        "error": bool(result.get("error")),
                    }
                )

            except Exception as e:
                error_msg = f"❌ Error: {str(e)}"
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": error_msg,
                        "artifacts": {},
                        "error": True,
                    }
                )
                st.session_state.messages_en.append(
                    {"role": "assistant", "content": error_msg}
                )

            finally:
                trace_placeholder.empty()

    st.rerun()
