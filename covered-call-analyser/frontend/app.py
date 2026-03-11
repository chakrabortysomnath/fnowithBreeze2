"""
frontend/app.py — Streamlit frontend (Phase 4).

Phase 1 stub: shows a placeholder page confirming the backend is reachable.
Full UI implemented in Phase 4.

Run locally:
    streamlit run frontend/app.py

Environment variables:
    BACKEND_URL — FastAPI backend base URL (default: http://localhost:8000)
"""

import os
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Covered Call Analyser",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Covered Call Strategy Analyser")
st.caption("Phase 1 — Backend connectivity stub. Full UI coming in Phase 4.")

st.divider()

# ---------------------------------------------------------------------------
# Backend health check
# ---------------------------------------------------------------------------

st.subheader("Backend Status")

try:
    resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
    resp.raise_for_status()
    data = resp.json()

    if data.get("breeze_connected"):
        st.success(
            f"✅ Backend is reachable at `{BACKEND_URL}` | "
            f"Breeze API: **Connected**"
        )
    else:
        st.warning(
            f"⚠️ Backend is reachable at `{BACKEND_URL}` but "
            f"Breeze API is **not connected**. "
            f"Check your session token.\n\n"
            f"Message: {data.get('message', 'No detail')}"
        )

except requests.exceptions.ConnectionError:
    st.error(
        f"❌ Cannot reach backend at `{BACKEND_URL}`. "
        "Is the FastAPI server running?\n\n"
        "Start it with: `uvicorn backend.main:app --reload --port 8000`"
    )
except Exception as exc:
    st.error(f"❌ Unexpected error checking backend: {exc}")

st.divider()

# ---------------------------------------------------------------------------
# Quick quote test (Phase 1 smoke test)
# ---------------------------------------------------------------------------

st.subheader("Quick Quote Test")
st.caption("Enter a symbol to test the live CMP endpoint.")

col1, col2 = st.columns([2, 1])
with col1:
    symbol = st.text_input(
        "NSE Symbol",
        value="RELIANCE",
        help="E.g. RELIANCE, INFY, TCS. For M&M use M%26M in the URL (the box handles it).",
    )
with col2:
    st.write("")  # spacer
    fetch = st.button("Fetch CMP", use_container_width=True)

if fetch and symbol:
    # URL-encode & in symbol
    encoded = symbol.replace("&", "%26")
    try:
        r = requests.get(f"{BACKEND_URL}/quote/{encoded}", timeout=10)
        if r.status_code == 200:
            q = r.json()
            st.metric(
                label=f"CMP — {q['symbol']}",
                value=f"₹{q['cmp']:,.2f}",
                help=f"Fetched at {q['timestamp']}",
            )
        else:
            st.error(f"Error {r.status_code}: {r.json().get('detail', 'Unknown error')}")
    except Exception as exc:
        st.error(f"Request failed: {exc}")

st.divider()
st.info("🚧 Full analysis UI (strike selection, P&L table, charts) coming in Phase 4.")
