"""
frontend/app.py — Breezy F&O UI.

Layout mirrors the design template:
  Left  — symbol input + Analyse button + results table
  Right — bar chart (strike/premium comparison) + line chart (P&L payoff)

Environment variables:
    BACKEND_URL — FastAPI backend base URL (default: http://localhost:8000)
"""

import os
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# Brand palette — matches design template
BLUE_PRIMARY = "#1A56DB"
TEAL_LIGHT   = "#7FD7D0"
TEAL_MED     = "#2AB0AA"
NAVY         = "#1B3D8F"
TABLE_HEADER = "#C5CBF5"
INPUT_BG     = "#D4E8F7"
GRID_COLOR   = "#E5E7EB"

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Breezy F&O",
    page_icon="🤏",
    layout="wide",
)

st.markdown(f"""
<style>
  /* hide Streamlit chrome */
  #MainMenu, footer, header {{visibility: hidden;}}

  /* brand header */
  .brand-wrap {{
    display: flex;
    align-items: center;
    gap: 18px;
    margin-bottom: 6px;
  }}
  .brand-icon {{
    font-size: 52px;
    line-height: 1;
  }}
  .brand-title {{
    font-size: 42px;
    font-weight: 900;
    color: {BLUE_PRIMARY};
    letter-spacing: -1px;
    font-family: "Segoe UI", Inter, sans-serif;
  }}

  /* status pills */
  .pill-ok  {{
    display: inline-block;
    background: #D1FAE5; color: #065F46;
    border-radius: 9999px; padding: 3px 14px;
    font-size: 13px; font-weight: 600; margin-bottom: 16px;
  }}
  .pill-warn {{
    display: inline-block;
    background: #FEF3C7; color: #92400E;
    border-radius: 9999px; padding: 3px 14px;
    font-size: 13px; font-weight: 600; margin-bottom: 16px;
  }}
  .pill-err {{
    display: inline-block;
    background: #FEE2E2; color: #991B1B;
    border-radius: 9999px; padding: 3px 14px;
    font-size: 13px; font-weight: 600; margin-bottom: 16px;
  }}

  /* primary button — pill shape */
  div[data-testid="stButton"] > button {{
    background-color: {BLUE_PRIMARY} !important;
    color: white !important;
    border-radius: 9999px !important;
    border: none !important;
    font-weight: 700 !important;
    font-size: 15px !important;
    height: 44px !important;
    width: 100% !important;
    margin-top: 2px;
  }}
  div[data-testid="stButton"] > button:hover {{
    background-color: #1648C0 !important;
  }}

  /* text input — light blue fill */
  div[data-testid="stTextInput"] input {{
    background-color: {INPUT_BG} !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 15px !important;
    height: 44px !important;
  }}

  /* dataframe header row */
  thead tr th {{
    background-color: {TABLE_HEADER} !important;
    color: #1A1A4E !important;
    font-weight: 700 !important;
  }}
</style>
""", unsafe_allow_html=True)

# ── Brand header ──────────────────────────────────────────────────────────────

st.markdown("""
<div class="brand-wrap">
  <span class="brand-icon">🤏</span>
  <span class="brand-title">Breezy F&amp;O</span>
</div>
""", unsafe_allow_html=True)

# ── Backend health pill ───────────────────────────────────────────────────────

try:
    h = requests.get(f"{BACKEND_URL}/health", timeout=5).json()
    if h.get("breeze_connected"):
        st.markdown('<span class="pill-ok">● Breeze connected</span>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<span class="pill-warn">⚠ Backend reachable — Breeze disconnected. '
            'Refresh session token.</span>',
            unsafe_allow_html=True,
        )
except Exception:
    st.markdown(
        '<span class="pill-err">✕ Backend unreachable</span>',
        unsafe_allow_html=True,
    )

# ── Session state ─────────────────────────────────────────────────────────────

if "quote" not in st.session_state:
    st.session_state.quote = None

# ── Two-column layout ─────────────────────────────────────────────────────────

left, right = st.columns([1, 1.25], gap="large")

# ─────────────────────────────────────────────────────────────────────────────
# LEFT — input row + results table
# ─────────────────────────────────────────────────────────────────────────────

with left:
    inp_col, btn_col = st.columns([3, 1.1])

    with inp_col:
        symbol = st.text_input(
            label="symbol",
            value="RELIANCE",
            placeholder="NSE symbol — e.g. RELIANCE",
            label_visibility="collapsed",
        )

    with btn_col:
        fetch = st.button("Analyse", use_container_width=True)

    if fetch and symbol:
        encoded = symbol.strip().upper().replace("&", "%26")
        try:
            r = requests.get(f"{BACKEND_URL}/quote/{encoded}", timeout=10)
            if r.status_code == 200:
                st.session_state.quote = r.json()
            else:
                st.error(f"Error {r.status_code}: {r.json().get('detail', 'Unknown')}")
        except Exception as exc:
            st.error(f"Request failed: {exc}")

    q = st.session_state.quote

    if q:
        cmp = q["cmp"]
        atm = round(cmp / 50) * 50
        otm = atm + 50
        # Placeholder premium estimate until option chain endpoint is live
        atm_prem = round(cmp * 0.03, 2)
        otm_prem = round(cmp * 0.015, 2)

        table_df = pd.DataFrame([
            {"":  "Symbol",       "Details": q["symbol"],             "Note": "NSE"},
            {"":  "CMP",          "Details": f"₹{cmp:,.2f}",          "Note": "Live"},
            {"":  "ATM Strike",   "Details": f"₹{atm:,}",             "Note": "Est."},
            {"":  "OTM Strike",   "Details": f"₹{otm:,}",             "Note": "Est."},
            {"":  "ATM Premium",  "Details": f"₹{atm_prem:,.2f}",     "Note": "Est."},
            {"":  "Timestamp",    "Details": q.get("timestamp", "—"), "Note": "IST"},
        ])
    else:
        table_df = pd.DataFrame([
            {"": "Symbol",      "Details": "—", "Note": "—"},
            {"": "CMP",         "Details": "—", "Note": "—"},
            {"": "ATM Strike",  "Details": "—", "Note": "—"},
            {"": "OTM Strike",  "Details": "—", "Note": "—"},
            {"": "ATM Premium", "Details": "—", "Note": "—"},
            {"": "Timestamp",   "Details": "—", "Note": "—"},
        ])

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        height=245,
    )

# ─────────────────────────────────────────────────────────────────────────────
# RIGHT — bar chart + line chart
# ─────────────────────────────────────────────────────────────────────────────

def _base_layout(height=240):
    return dict(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=40, b=36),
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#374151"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.05,
            xanchor="left", x=0, font=dict(size=12),
        ),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
        height=height,
    )

with right:
    q = st.session_state.quote

    # ── Bar chart — CMP vs strike price levels ────────────────────────────────

    if q:
        cmp = q["cmp"]
        atm = round(cmp / 50) * 50
        x_labels    = ["CMP", "ATM Strike", "OTM +50", "OTM +100"]
        series1_bar = [cmp,  0,         0,           0]
        series2_bar = [0,    atm,       atm + 50,    atm + 100]
    else:
        x_labels    = ["Item 1", "Item 2", "Item 3"]
        series1_bar = [3, 8, 16]
        series2_bar = [6, 14, 18]

    bar_fig = go.Figure()
    bar_fig.add_trace(go.Bar(
        name="Series 1", x=x_labels, y=series1_bar,
        marker_color=TEAL_LIGHT,
    ))
    bar_fig.add_trace(go.Bar(
        name="Series 2", x=x_labels, y=series2_bar,
        marker_color=TEAL_MED,
    ))
    bar_fig.update_layout(**_base_layout(), barmode="group")
    st.plotly_chart(bar_fig, use_container_width=True, config={"displayModeBar": False})

    # ── Line chart — P&L payoff at expiry ─────────────────────────────────────

    if q:
        cmp   = q["cmp"]
        lot   = 250          # placeholder lot size
        prem  = round(cmp * 0.03, 2)
        spots = [round(cmp * (0.88 + 0.06 * i)) for i in range(5)]
        s_labels = [f"₹{s:,}" for s in spots]

        # Long stock P&L
        pl_stock = [(s - cmp) * lot for s in spots]
        # Covered call (long stock + short ATM call)
        atm = round(cmp / 50) * 50
        pl_cc = [(min(s, atm) - cmp + prem) * lot for s in spots]
        # Short call alone
        pl_sc = [(prem - max(s - atm, 0)) * lot for s in spots]
    else:
        s_labels = [f"Item {i}" for i in range(1, 6)]
        pl_stock = [12, 11, 38, 31, 32]
        pl_cc    = [19, 30, 25, 40, 42]
        pl_sc    = [20,  5, 20, 15, 50]

    line_fig = go.Figure()
    line_fig.add_trace(go.Scatter(
        name="Series 1", x=s_labels, y=pl_stock,
        mode="lines+markers",
        line=dict(color=TEAL_LIGHT, width=2),
        marker=dict(size=6),
    ))
    line_fig.add_trace(go.Scatter(
        name="Series 2", x=s_labels, y=pl_cc,
        mode="lines+markers",
        line=dict(color=TEAL_MED, width=2),
        marker=dict(size=6),
    ))
    line_fig.add_trace(go.Scatter(
        name="Series 3", x=s_labels, y=pl_sc,
        mode="lines+markers",
        line=dict(color=NAVY, width=2),
        marker=dict(size=6),
    ))
    line_fig.update_layout(**_base_layout())
    st.plotly_chart(line_fig, use_container_width=True, config={"displayModeBar": False})
