# health.py - Lightweight health check endpoint
# This page loads quickly without initializing the full agent/LLM
import streamlit as st

st.set_page_config(page_title="Health Check", layout="centered")

# Simple health check response
st.title("✅ Service Healthy")
st.write("Application is running")
