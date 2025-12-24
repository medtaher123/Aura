# streamlit_app.py
import sys
from pathlib import Path
import traceback
import streamlit as st
from PIL import Image

# Ensure project root is on sys.path so absolute imports work when running via `streamlit run src/ui/streamlit_app.py`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.agent_runner import invoke_agent, coerce_tool_response
from src.ui.html_artifacts import display_html_file
from src.tools.contracts import make_tool_response


MAPS_DIR = PROJECT_ROOT / "src" / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

from src.services import (
    create_agent_executor,
    detect_and_translate_to_english,
    translate_from_english,
)

# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
st.set_page_config(page_title="STAC & Fire Chatbot", layout="centered")

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
    # Store user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    # Process
    with st.spinner("⏳ Processing..."):
        try:
            english_query, detected_lang = detect_and_translate_to_english(user_input)
            st.session_state.last_lang = detected_lang

            agent_output = invoke_agent(agent_executor, english_query)

            result = coerce_tool_response(agent_output)
            if isinstance(result.get("message"), str):
                result["message"] = translate_from_english(result["message"], detected_lang)

            st.session_state.messages.append({"role": "assistant", "content": str(result.get("message", ""))})

        except Exception as e:
            # Ensure errors are visible in server logs AND do not crash the UI.
            traceback.print_exc()
            error_msg = f"❌ Error: {str(e)}"
            result = make_tool_response(
                tool_name="ui",
                message=error_msg,
                artifacts={"maps": [], "thumbnails": [], "urls": []},
                error=True,
            )
            st.session_state.messages.append({"role": "assistant", "content": error_msg})


    # ---------------------------------------------------
    # DISPLAY ASSISTANT RESPONSE
    # ---------------------------------------------------
    with st.chat_message("assistant"):
        # Defensive: coerce any unexpected shapes into a ToolResponse.
        if not isinstance(result, dict):
            result = make_tool_response(
                tool_name="ui",
                message=str(result),
                artifacts={"maps": [], "thumbnails": [], "urls": []},
                error=True,
            )

        if result.get("error"):
            st.error(result.get("message") or "An error occurred.")
        else:
            st.write(result.get("message") or "")

        artifacts = result.get("artifacts") or {}
        maps = artifacts.get("maps") or []
        thumbnails = artifacts.get("thumbnails") or []

        for name in maps:
            if isinstance(name, str) and name.endswith(".html"):
                display_html_file(name, maps_dir=MAPS_DIR, project_root=PROJECT_ROOT)

        if thumbnails:
            st.write("### Thumbnails")
            for url in thumbnails:
                if isinstance(url, str) and url:
                    st.image(url, width=300)