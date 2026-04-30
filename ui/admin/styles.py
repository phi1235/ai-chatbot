from __future__ import annotations

import streamlit as st


def apply_styles() -> None:
    st.markdown(
        """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    :root {
        --canvas: #faf9f7;
        --surface: #ffffff;
        --text: #1f1f1f;
        --text-muted: #6b6b6b;
        --text-subtle: #9a9a9a;
        --border: #ececec;
        --border-strong: #d9d9d9;
        --accent: #cc785c;
        --accent-soft: #f6efeb;
        --ok: #16a34a;
        --warn: #d97706;
        --danger: #dc2626;
    }

    .stApp {
        background: var(--canvas);
        color: var(--text);
        font-family: 'Inter', -apple-system, sans-serif;
    }
    .block-container {
        max-width: 1200px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    #MainMenu, footer { visibility: hidden; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stHeader"] {
        background: transparent;
        height: auto;
    }

    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
        min-width: 260px !important;
        max-width: 280px !important;
        width: 260px !important;
        transform: translateX(0) !important;
        visibility: visible !important;
        display: block !important;
        position: relative !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] {
        margin-left: 0 !important;
        transform: translateX(0) !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding: 1.2rem 0.8rem;
    }
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }

    .brand {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.4rem 0.6rem 1.2rem 0.6rem;
        border-bottom: 1px solid var(--border);
        margin-bottom: 1rem;
    }
    .brand-mark {
        width: 32px; height: 32px;
        border-radius: 8px;
        background: var(--accent);
        color: white;
        display: flex; align-items: center; justify-content: center;
        font-weight: 700;
    }
    .brand-title {
        font-size: 0.98rem;
        font-weight: 700;
        margin: 0;
    }
    .brand-sub {
        font-size: 0.78rem;
        color: var(--text-muted);
        margin: 0;
    }

    .page-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1rem;
        margin-bottom: 1.2rem;
    }
    .page-title {
        font-size: 1.8rem;
        line-height: 1.1;
        margin: 0;
        letter-spacing: -0.02em;
    }
    .page-subtitle {
        color: var(--text-muted);
        margin-top: 0.35rem;
        margin-bottom: 0;
    }
    .card-title {
        font-size: 0.92rem;
        font-weight: 700;
        margin-bottom: 0.6rem;
        color: var(--text);
    }

    .status-row {
        display: grid;
        grid-template-columns: auto auto minmax(160px, 1.4fr) minmax(120px, 1fr);
        gap: 0.5rem;
        align-items: center;
        padding: 0.6rem 0.75rem;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: var(--surface);
        margin-bottom: 0.45rem;
    }
    .status-row .badge {
        font-size: 0.74rem;
        font-weight: 700;
    }
    .status-row .topic,
    .status-row .detail {
        color: var(--text-muted);
        font-size: 0.85rem;
    }
    .status-row .url {
        font-size: 0.88rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .status-row.ok .badge { color: var(--ok); }
    .status-row.warn .badge { color: var(--warn); }
    .status-row.error .badge { color: var(--danger); }
    </style>
    """,
        unsafe_allow_html=True,
    )
