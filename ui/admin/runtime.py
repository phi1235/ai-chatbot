from __future__ import annotations

import os

import httpx
import streamlit as st

DEFAULT_API_URL = os.getenv("DEFAULT_API_URL") or f"http://localhost:{os.getenv('UVICORN_PORT', '8000')}"


@st.cache_resource

def http() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))



def api_url() -> str:
    return st.session_state.get("api_url", DEFAULT_API_URL).rstrip("/")
