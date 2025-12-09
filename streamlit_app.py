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
    "fr": {
        "results_for": "Results for collection",
        "cloud": "Cloud",
        "date": "Date",
    },
    "en": {
        "results_for": "Results for collection",
        "cloud": "Cloud",
        "date": "Date",
    },
    "es": {
        "results_for": "Resultados para la colección",
        "cloud": "Nube",
        "date": "Fecha",
    },
    "ar": {
        "results_for": "نتائج المجموعة",
        "cloud": "السحب",
        "date": "التاريخ",
    },
    "it": {
        "results_for": "Risultati per la collezione",
        "cloud": "Nuvolosità",
        "date": "Data",
    },
    "de": {
        "results_for": "Ergebnisse für die Sammlung",
        "cloud": "Wolken",
        "date": "Datum",
    },
}

def get_labels(lang_code: str):
    """Return labels adapted to the detected language."""
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
# FORM
# ---------------------------------------------------
with st.form("query_form"):
    user_input = st.text_input("📥 Enter your request:")
    submitted = st.form_submit_button("🔍 Search")

# Initialize agent
if "agent_executor" not in st.session_state:
    st.session_state.agent_executor = create_agent_executor()

agent_executor = st.session_state.agent_executor

# Memory
st.session_state.setdefault("last_result", None)
st.session_state.setdefault("last_feedback", None)
st.session_state.setdefault("last_lang", "en")  # language of the user request


# Satellite query detection
def is_satellite_query(text: str) -> bool:
    text = text.lower()
    keywords = [
        "sentinel", "modis", "viirs", "ndvi", "stac",
        "satellite", "satellites",
        "صور فضائية", "قمر صناعي", "الاقمار الصناعية",
        "satélite", "satelitales", "satellitare", "satelliten",
    ]
    return any(k in text for k in keywords)


# Extract HTML names
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


# Multilingual pivot pipeline
def translate_query_pipeline(user_text):
    """
    1) Detect user language
    2) Translate to English
    """
    en, detected_lang = detect_and_translate_to_english(user_text)
    return en, detected_lang

def translate_to_original_query_pipeline(user_text,detected_lang):
    """
    1) Translate to the user language using translate_from_english_tool
    """
    translated_text = translate_from_english(user_text,detected_lang)
    return translated_text

# PROCESSING
if submitted and user_input:
    with st.spinner("⏳ Processing..."):
        try:
            english_query, detected_lang = translate_query_pipeline(user_input)
            st.session_state["last_lang"] = detected_lang

            # STAC direct query
            if is_satellite_query(english_query):
                raw = run_query_direct(english_query)
                result = raw

            else:
                # Conversational agent → must return JSON according to your rules
                response = agent_executor.invoke({"input": english_query})

                if isinstance(response, dict):
                    json_output = response.get("output", str(response))
                else:
                    json_output = str(response)

                # Keep JSON structure intact and only translate the message field
                result = json_output
                result=translate_to_original_query_pipeline(result,detected_lang)

            st.session_state.last_result = result
            st.session_state.last_feedback = {"type": "success", "text": "✅ Request processed successfully!"}

        except Exception as e:
            st.session_state.last_result = None
            st.session_state.last_feedback = {
                "type": "error",
                "text": f"❌ Error while processing request: {str(e)}",
            }

# ---------------------------------------------------
# FEEDBACK DISPLAY
# ---------------------------------------------------
feedback = st.session_state.get("last_feedback")

if feedback:
    msg_type = feedback.get("type", "info")
    msg = feedback.get("text", "")

    if msg_type == "success":
        st.success(msg)
    elif msg_type == "error":
        st.error(msg)
    elif msg_type == "warning":
        st.warning(msg)
    else:
        st.info(msg)

    if feedback.get("hint"):
        st.info(feedback["hint"])
    if feedback.get("caption"):
        st.caption(feedback["caption"])

# ---------------------------------------------------
# RESULT DISPLAY
# ---------------------------------------------------
result = st.session_state.last_result
user_lang = st.session_state.get("last_lang", "en")
labels = get_labels(user_lang)

if result is not None:

    # --------- JSON ERROR CASE ---------
    if isinstance(result, dict) and result.get("error") is True:
        st.error(result.get("message", "Unknown error."))
        st.stop()

    # --------- STAC IMAGES ---------
    if isinstance(result, dict) and "images" in result:
        st.write(f"### {labels['results_for']} `{result.get('collection', 'unknown')}`:")

        for img in result["images"]:
            cloud = img.get("cloud_cover", "N/A")
            caption = (
                f"🗓️ {labels['date']}: {img['date']} | "
                f"☁️ {labels['cloud']}: {cloud if not isinstance(cloud, float) else f'{cloud:.2f}%'}"
            )
            thumb = img.get("thumbnail") or img.get("vignette") or img.get("url") or ""
            st.image(thumb, caption=caption, width=300)

        st.stop()

    # --------- FOLIUM MAP ---------
    if isinstance(result, dict) and "folium_map" in result:
        st.write("### Generated Map:")
        fmap = result["folium_map"]
        if hasattr(fmap, "get_root"):
            components.html(fmap.get_root().render(), height=600)
        else:
            st.warning("⚠️ Could not render map.")
        st.stop()

    # --------- HTML file detection ---------
    if isinstance(result, str) and (result.endswith(".html") or ".html" in result):
        st.write("### Result:")
        st.write(result)
        display_all_html_from_text(result)
        st.stop()

    # --------- JSON Result with message or map ---------
    if isinstance(result, dict) and result.get("message"):
        st.write("### Result:")
        st.write(result.get("message"))
        # If map_file is provided, try to render it
        map_file = result.get("map_file") or result.get("map") or result.get("folium_map")
        if isinstance(map_file, str) and map_file.endswith(".html"):
            display_all_html_from_text(map_file)
        st.stop()

    # --------- JSON or Text Response ---------
    st.write("### Result:")
    st.write(result)
