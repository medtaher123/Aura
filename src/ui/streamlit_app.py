"""Streamlit UI for MetaplanetLLM.

Renders assistant responses, including map artifacts (HTML or Pydeck specs).
"""

import sys
import os
from pathlib import Path
import traceback

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
from src.tools.contracts import make_tool_response

MAPS_DIR = PROJECT_ROOT / "src" / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

from src.services import (
    create_agent_executor,
    detect_and_translate_to_english,
    translate_from_english,
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
        tooltip=tooltip,
    )
    st.pydeck_chart(deck, use_container_width=True, height=item.get("height", 450))


# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
st.set_page_config(page_title="STAC & Fire Chatbot", layout="wide")

logo = Image.open(Path(__file__).resolve().parent / "assets" / "metaplanet_sas_logo.jpeg")
st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
st.image(logo, width=150)
st.markdown("</div>", unsafe_allow_html=True)

st.title("🛰️🔥 Metaplanet Earth Agent")


# ---------------------------------------------------
# SESSION VARIABLES (Chat history & agent)
# ---------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# Store an English-only chat history for the agent context.
if "messages_en" not in st.session_state:
    st.session_state.messages_en = []

if "agent_executor" not in st.session_state:
    st.session_state.agent_executor = create_agent_executor()

if "last_lang" not in st.session_state:
    st.session_state.last_lang = "en"

agent_executor = st.session_state.agent_executor


# ---------------------------------------------------
# DISPLAY CHAT HISTORY
# ---------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


# ---------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------
user_input = st.chat_input("Ask me anything about Earth observation or STAC...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    with st.spinner("⏳ Processing..."):
        try:
            english_query, detected_lang = detect_and_translate_to_english(user_input)
            st.session_state.last_lang = detected_lang

            # Keep the agent-facing conversation in English.
            st.session_state.messages_en.append({"role": "user", "content": english_query})

            # Exclude the current user turn from history to avoid duplication.
            history_for_agent = st.session_state.messages_en[:-1]
            agent_output = invoke_agent(agent_executor, english_query, chat_history=history_for_agent)
            result = coerce_tool_response(agent_output)

            assistant_message_en = result.get("message") if isinstance(result, dict) else ""
            if not isinstance(assistant_message_en, str):
                assistant_message_en = str(assistant_message_en)

            if isinstance(result.get("message"), str):
                result["message"] = translate_from_english(result["message"], detected_lang)

            # Persist assistant message in English for future turns.
            st.session_state.messages_en.append(
                {"role": "assistant", "content": assistant_message_en}
            )

            st.session_state.messages.append(
                {"role": "assistant", "content": str(result.get("message", ""))}
            )

        except Exception as e:
            traceback.print_exc()
            error_msg = f"❌ Error: {str(e)}"
            result = make_tool_response(
                tool_name="ui",
                message=error_msg,
                artifacts={"maps": [], "thumbnails": [], "urls": []},
                error=True,
            )
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
            st.session_state.messages_en.append({"role": "assistant", "content": error_msg})

    # ---------------------------------------------------
    # DISPLAY ASSISTANT RESPONSE
    # ---------------------------------------------------
    with st.chat_message("assistant"):
        if not isinstance(result, dict):
            result = make_tool_response(
                tool_name="ui",
                message=str(result),
                artifacts={"maps": [], "thumbnails": [], "urls": []},
                error=True,
            )

        artifacts = result.get("artifacts") or {}
        maps = artifacts.get("maps") or []
        thumbnails = artifacts.get("thumbnails") or []

        has_map = any(
            (isinstance(x, str) and x.endswith(".html"))
            or (
                isinstance(x, dict)
                and isinstance(x.get("view_state"), dict)
                and (isinstance(x.get("points"), list) or isinstance(x.get("layers"), list))
            )
            for x in maps
        )

        # Layout: text left, map right when a map exists.
        if result.get("error") or not has_map:
            if result.get("error"):
                st.error(result.get("message") or "An error occurred.")
            else:
                st.write(result.get("message") or "")

            # Keep thumbnails visible even when there is no map.
            if thumbnails:
                st.write("### Satellite Images:")
                for url in thumbnails:
                    if isinstance(url, str) and url:
                        st.image(url, width=300)

        else:
            # Give the map more horizontal room.
            col_text, col_map = st.columns([2, 3], vertical_alignment="top")
            with col_text:
                st.write(result.get("message") or "")

            with col_map:
                for item in maps:
                    if isinstance(item, dict) and isinstance(item.get("view_state"), dict):
                        _render_pydeck_map_spec(item)

                if thumbnails:
                    st.write("### Satellite Images:")
                    for url in thumbnails:
                        if isinstance(url, str) and url:
                            st.image(url, width=300)