# streamlit_app.py
import streamlit as st
from PIL import Image
from nodes import run_query_direct, create_agent_executor
import streamlit.components.v1 as components
import re
import os
from translate import detect_and_translate_to_english, translate_from_english

# ---------------------------------------------------
# MULTILINGUAL LABELS (English defaults)
# ---------------------------------------------------
LABELS = {
    "fr": {"results_for": "Results for collection", "cloud": "Cloud", "date": "Date"},
    "en": {"results_for": "Results for collection", "cloud": "Cloud", "date": "Date"},
    "es": {"results_for": "Resultados para la colección", "cloud": "Nube", "date": "Fecha"},
    "ar": {"results_for": "نتائج المجموعة", "cloud": "السحب", "date": "التاريخ"},
    "it": {"results_for": "Risultati per la collezione", "cloud": "Nuvolosità", "date": "Data"},
    "de": {"results_for": "Ergebnisse für die Sammlung", "cloud": "Wolken", "date": "Datum"},
}

def get_labels(lang_code: str):
    base = lang_code.split("-")[0] if lang_code else "en"
    return LABELS.get(base, LABELS["en"])


# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
st.set_page_config(page_title="STAC & Fire Chatbot", layout="centered")

logo = Image.open("metaplanet_sas_logo.jpeg")
st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
st.image(logo, width=150)
st.markdown("</div>", unsafe_allow_html=True)

st.title("🛰️🔥 Metaplanet Earth Agent")

# ---------------------------------------------------
# SESSION VARIABLES (Chat history & agent)
# ---------------------------------------------------
if "messages" not in st.session_state:
    print("Initializing chat messages...")
    st.session_state.messages = []

if "agent_executor" not in st.session_state:
    st.session_state.agent_executor = create_agent_executor()

if "last_lang" not in st.session_state:
    st.session_state.last_lang = "en"
print("Session state:", st.session_state)
if "messages" in st.session_state:
    print('Loaded messages from session state:', st.session_state.messages)
    
agent_executor = st.session_state.agent_executor


# ---------------------------------------------------
# HELPERS
# ---------------------------------------------------
def is_satellite_query(text: str) -> bool:
    text = text.lower()
    keywords = [
        "sentinel", "modis", "viirs", "ndvi", "stac",
        "satellite", "satellites",
        "صور فضائية", "قمر صناعي", "الاقمار الصناعية",
        "satélite", "satelitales", "satellitare", "satelliten",
    ]
    return any(k in text for k in keywords)

def inject_into_memory(agent_executor, user_text, assistant_text):
    memory = agent_executor.memory
    memory.save_context(
        {"input": user_text},
        {"output": assistant_text}
    )
    
def extract_all_html_filenames(text: str):
    return re.findall(r'([\w\-]+\.html)', text)


def display_html_file(filename: str):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            html = f.read()
        components.html(html, height=600, width=800)
    else:
        st.warning(f"⚠️ HTML file `{filename}` does not exist.")


def display_all_html_from_text(text: str):
    found = extract_all_html_filenames(text)
    html_files = [f for f in os.listdir(".") if f.endswith(".html")]

    for name in found:
        if name in html_files:
            st.write(f"### Displaying `{name}`:")
            display_html_file(name)
        else:
            st.warning(f"⚠️ HTML file `{name}` not found.")


def translate_query_pipeline(user_text):
    en, detected_lang = detect_and_translate_to_english(user_text)
    return en, detected_lang


def translate_to_original_query_pipeline(user_text, detected_lang):
    return translate_from_english(user_text, detected_lang)


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
            english_query, detected_lang = translate_query_pipeline(user_input)
            st.session_state.last_lang = detected_lang

            # Satellite detection
            if is_satellite_query(english_query):
                result = run_query_direct(english_query)

                # 🔑 Inject summary into LLM memory
                inject_into_memory(
                    agent_executor,
                    english_query,
                    result["message"] if isinstance(result, dict) and "message" in result else str(result)
                )

            else:
                response = agent_executor.invoke({"input": english_query})
                if isinstance(response, dict):
                    json_output = response.get("output", str(response))
                else:
                    json_output = str(response)
                result = translate_to_original_query_pipeline(json_output, detected_lang)

            # Store assistant message placeholder
            st.session_state.messages.append({"role": "assistant", "content": str(result)})

        except Exception as e:
            error_msg = f"❌ Error: {str(e)}"
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
            result = error_msg


    # ---------------------------------------------------
    # DISPLAY ASSISTANT RESPONSE
    # ---------------------------------------------------
    with st.chat_message("assistant"):
        # Handle structured results
        if isinstance(result, dict) and result.get("error"):
            st.error(result["message"])

        elif isinstance(result, dict) and "images" in result:
            labels = get_labels(st.session_state.last_lang)
            st.write(f"### {labels['results_for']} `{result.get('collection', 'unknown')}`:")
            for img in result["images"]:
                cloud = img.get("cloud_cover", "N/A")
                caption = f"🗓️ {labels['date']}: {img['date']} | ☁️ {labels['cloud']}: {cloud}"
                st.image(img.get("thumbnail") or img.get("url") or "", caption=caption, width=300)

        elif isinstance(result, dict) and "folium_map" in result:
            st.write("### Generated Map:")
            fmap = result["folium_map"]
            components.html(fmap.get_root().render(), height=600)

        elif isinstance(result, str) and (result.endswith(".html") or ".html" in result):
            st.write(result)
            display_all_html_from_text(result)

        elif isinstance(result, dict) and "message" in result:
            st.write(result["message"])
            map_file = result.get("map_file") or result.get("map")
            if isinstance(map_file, str) and map_file.endswith(".html"):
                display_all_html_from_text(map_file)

        else:
            st.write(result)
