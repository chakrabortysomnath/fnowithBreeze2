"""
frontend/app.py — Breezy F&O covered call analyser UI (Phase 4).

Layout:
  Left  — symbol + expiry form, position inputs, Analyse button, results table
  Right — annualised-yield bar chart + P&L payoff line chart

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

# Brand palette
BLUE_PRIMARY = "#1A56DB"
TEAL_LIGHT   = "#7FD7D0"
TEAL_MED     = "#2AB0AA"
NAVY         = "#1B3D8F"
ORANGE       = "#F97316"
TABLE_HEADER = "#C5CBF5"
INPUT_BG     = "#D4E8F7"
GRID_COLOR   = "#E5E7EB"

STRIKE_COLORS = {
    "ITM":   NAVY,
    "ATM":   BLUE_PRIMARY,
    "OTM+1": TEAL_MED,
    "OTM+2": TEAL_LIGHT,
}

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Breezy F&O",
    page_icon="🤏",
    layout="wide",
)

st.markdown(f"""
<style>
  #MainMenu, footer, header {{visibility: hidden;}}

  .brand-wrap {{
    display: flex; align-items: center; gap: 18px; margin-bottom: 6px;
  }}
  .brand-icon  {{ font-size: 52px; line-height: 1; }}
  .brand-title {{
    font-size: 42px; font-weight: 900; color: {BLUE_PRIMARY};
    letter-spacing: -1px; font-family: "Segoe UI", Inter, sans-serif;
  }}

  .pill-ok   {{ display:inline-block; background:#D1FAE5; color:#065F46;
                border-radius:9999px; padding:3px 14px;
                font-size:13px; font-weight:600; margin-bottom:16px; }}
  .pill-warn {{ display:inline-block; background:#FEF3C7; color:#92400E;
                border-radius:9999px; padding:3px 14px;
                font-size:13px; font-weight:600; margin-bottom:16px; }}
  .pill-err  {{ display:inline-block; background:#FEE2E2; color:#991B1B;
                border-radius:9999px; padding:3px 14px;
                font-size:13px; font-weight:600; margin-bottom:16px; }}

  div[data-testid="stButton"] > button {{
    background-color: {BLUE_PRIMARY} !important; color: white !important;
    border-radius: 9999px !important; border: none !important;
    font-weight: 700 !important; font-size: 15px !important;
    height: 44px !important; width: 100% !important; margin-top: 2px;
  }}
  div[data-testid="stButton"] > button:hover {{
    background-color: #1648C0 !important;
  }}

  div[data-testid="stTextInput"] input,
  div[data-testid="stNumberInput"] input {{
    background-color: {INPUT_BG} !important;
    border: none !important; border-radius: 8px !important;
    font-size: 15px !important;
  }}

  thead tr th {{
    background-color: {TABLE_HEADER} !important;
    color: #1A1A4E !important; font-weight: 700 !important;
  }}

  .metric-card {{
    background: #F0F4FF; border-radius: 10px; padding: 10px 16px;
    margin-bottom: 6px; display: inline-block; min-width: 120px;
    text-align: center;
  }}
  .metric-label {{ font-size: 11px; color: #6B7280; font-weight: 600;
                   text-transform: uppercase; letter-spacing: 0.05em; }}
  .metric-value {{ font-size: 20px; font-weight: 800; color: {BLUE_PRIMARY}; }}
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
        st.markdown('<span class="pill-ok">● Breeze connected</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown(
            '<span class="pill-warn">⚠ Backend reachable — Breeze disconnected. '
            'Refresh session token.</span>', unsafe_allow_html=True,
        )
except Exception:
    st.markdown('<span class="pill-err">✕ Backend unreachable</span>',
                unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

for key, default in [
    ("expiries", []),
    ("symbol_loaded", ""),
    ("result", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Helpers ───────────────────────────────────────────────────────────────────

def _encode(sym: str) -> str:
    return sym.strip().upper().replace("&", "%26")


def _fetch_expiries(symbol: str) -> list[str]:
    r = requests.get(f"{BACKEND_URL}/expiries/{_encode(symbol)}", timeout=10)
    r.raise_for_status()
    return r.json()["expiries"]


def _fetch_analyse(payload: dict) -> dict:
    r = requests.post(f"{BACKEND_URL}/analyse", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def _fmt_inr(v) -> str:
    if v is None:
        return "—"
    return f"₹{v:,.2f}"


def _base_layout(height=280):
    return dict(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=40, b=36),
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#374151"),
        legend=dict(orientation="h", yanchor="bottom", y=1.05,
                    xanchor="left", x=0, font=dict(size=12)),
        height=height,
    )


# ── Two-column layout ─────────────────────────────────────────────────────────

left, right = st.columns([1, 1.35], gap="large")

# ─────────────────────────────────────────────────────────────────────────────
# LEFT — input form + results
# ─────────────────────────────────────────────────────────────────────────────

with left:

    # Row 1: symbol + Load Expiries
    sym_col, load_col = st.columns([3, 1.1])
    with sym_col:
        symbol = st.text_input(
            label="symbol", value="RELIANCE",
            placeholder="NSE symbol — e.g. RELIANCE",
            label_visibility="collapsed",
        )
    with load_col:
        load_clicked = st.button("Load ↓", use_container_width=True)

    if load_clicked and symbol:
        try:
            st.session_state.expiries = _fetch_expiries(symbol)
            st.session_state.symbol_loaded = symbol.strip().upper()
            st.session_state.result = None   # clear stale results
        except Exception as exc:
            st.error(f"Could not load expiries: {exc}")

    # Row 2: expiry selectbox (only shown once expiries are loaded)
    expiry_date = None
    if st.session_state.expiries:
        expiry_date = st.selectbox(
            "Expiry date",
            options=st.session_state.expiries,
            label_visibility="visible",
        )
    else:
        st.caption("Enter a symbol and press **Load ↓** to fetch expiry dates.")

    # Row 3: position inputs
    already_holds = st.checkbox("I already hold this stock")

    qty_held = 0
    avg_price = 0.0
    if already_holds:
        q_col, p_col = st.columns(2)
        with q_col:
            qty_held = st.number_input(
                "Shares held", min_value=0, step=1, value=250,
            )
        with p_col:
            avg_price = st.number_input(
                "Avg purchase price (₹)", min_value=0.0, step=0.5, value=0.0,
                help="Leave 0 to use live CMP as cost basis.",
            )

    # Advanced charges (expander, collapsed by default)
    with st.expander("Advanced: charges", expanded=False):
        brokerage = st.number_input(
            "Brokerage per lot (₹)", min_value=1.0, step=1.0, value=40.0,
        )
        stt_rate = st.number_input(
            "STT rate", min_value=0.0001, max_value=0.05,
            step=0.0001, value=0.001, format="%.4f",
        )
        gst_rate = st.number_input(
            "GST rate", min_value=0.01, max_value=0.30,
            step=0.01, value=0.18, format="%.2f",
        )

    # Analyse button
    analyse_clicked = st.button("Analyse", use_container_width=True,
                                disabled=(expiry_date is None))

    if analyse_clicked and expiry_date:
        with st.spinner("Fetching data and running analysis…"):
            try:
                st.session_state.result = _fetch_analyse({
                    "symbol":             st.session_state.symbol_loaded or symbol.strip().upper(),
                    "expiry_date":        expiry_date,
                    "already_holds":      already_holds,
                    "quantity_held":      qty_held,
                    "avg_purchase_price": avg_price,
                    "brokerage":          brokerage,
                    "stt_rate":           stt_rate,
                    "gst_rate":           gst_rate,
                })
            except requests.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.response.json().get("detail", "")
                except Exception:
                    pass
                st.error(f"Error {exc.response.status_code}: {detail or exc}")
            except Exception as exc:
                st.error(f"Request failed: {exc}")

    # ── Results ───────────────────────────────────────────────────────────────

    res = st.session_state.result

    if res:
        pos = res["position"]

        # Position summary metrics
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("CMP",         _fmt_inr(res["cmp"]))
        mc2.metric("Lots",        pos["lots"])
        mc3.metric("Shares",      pos["shares"])
        mc4.metric("Capital",     _fmt_inr(pos["total_cost"]))

        st.caption(
            f"Cost basis ₹{pos['cost_basis_per_share']:,.2f} · "
            f"Expiry {res['expiry_date']} · {res['days_to_expiry']} days · "
            f"Lot size {res['lot_size']}"
        )

        # Strike comparison table
        rows = []
        for s in res["strikes"]:
            rows.append({
                "Strike type":        s["strike_type"],
                "Strike (₹)":         f"₹{s['strike']:,.0f}",
                "Premium (₹)":        f"₹{s['premium']:,.2f}",
                "Net premium":        _fmt_inr(s["net_premium_total"]),
                "Breakeven":          _fmt_inr(s["breakeven"]),
                "Max profit":         _fmt_inr(s["max_profit_total"]),
                "Yield %":            f"{s['premium_yield_pct']:.2f}%",
                "Ann. yield %":       (
                    f"{s['annualised_yield_pct']:.1f}%"
                    if s["annualised_yield_pct"] is not None else "—"
                ),
                "Downside protect.":  f"{s['downside_protection_pct']:.2f}%",
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            height=185,
        )

    else:
        # Placeholder table while no result yet
        placeholder = pd.DataFrame([
            {"Strike type": t, "Strike (₹)": "—", "Net premium": "—",
             "Breakeven": "—", "Max profit": "—", "Ann. yield %": "—",
             "Downside protect.": "—"}
            for t in ("ITM", "ATM", "OTM+1", "OTM+2")
        ])
        st.dataframe(placeholder, use_container_width=True,
                     hide_index=True, height=185)


# ─────────────────────────────────────────────────────────────────────────────
# RIGHT — charts
# ─────────────────────────────────────────────────────────────────────────────

with right:
    res = st.session_state.result

    # ── Chart 1 — Annualised yield bar chart ──────────────────────────────────

    if res and res["strikes"]:
        strikes = res["strikes"]
        bar_x      = [s["strike_type"] for s in strikes]
        bar_y_ann  = [s["annualised_yield_pct"] or 0 for s in strikes]
        bar_y_prem = [s["premium_yield_pct"] for s in strikes]
        bar_colors = [STRIKE_COLORS.get(t, TEAL_MED) for t in bar_x]

        bar_fig = go.Figure()
        bar_fig.add_trace(go.Bar(
            name="Ann. yield %", x=bar_x, y=bar_y_ann,
            marker_color=bar_colors,
            text=[f"{v:.1f}%" for v in bar_y_ann],
            textposition="outside",
        ))
        bar_fig.add_trace(go.Bar(
            name="Period yield %", x=bar_x, y=bar_y_prem,
            marker_color=[TEAL_LIGHT] * len(bar_x),
            text=[f"{v:.2f}%" for v in bar_y_prem],
            textposition="outside",
        ))
        bar_fig.update_layout(
            **_base_layout(height=280),
            barmode="group",
            title=dict(text="Yield comparison by strike", font=dict(size=14)),
            yaxis=dict(title="Yield (%)", showgrid=True,
                       gridcolor=GRID_COLOR, zeroline=False),
        )
    else:
        # Placeholder chart
        bar_fig = go.Figure()
        bar_fig.add_trace(go.Bar(
            name="Ann. yield %",
            x=["ITM", "ATM", "OTM+1", "OTM+2"],
            y=[0, 0, 0, 0],
            marker_color=TEAL_LIGHT,
        ))
        bar_fig.update_layout(
            **_base_layout(height=280),
            title=dict(text="Yield comparison by strike (run Analyse to populate)",
                       font=dict(size=14)),
        )

    st.plotly_chart(bar_fig, use_container_width=True,
                    config={"displayModeBar": False})

    # ── Chart 2 — P&L payoff line chart ───────────────────────────────────────

    if res and res["strikes"]:
        # Strike selector (radio above the chart)
        strike_labels = [
            f"{s['strike_type']} ₹{s['strike']:,.0f}" for s in res["strikes"]
        ]
        # Show all strikes by default; let user filter via radio
        show_all = st.checkbox("Show all strikes on payoff chart", value=True)

        line_fig = go.Figure()
        cmp_val = res["cmp"]

        for i, s in enumerate(res["strikes"]):
            if not show_all and strike_labels[i] != strike_labels[0]:
                continue
            payoff = s["payoff"]
            xs = [p["price"] for p in payoff]
            ys = [p["pl"]    for p in payoff]
            color = STRIKE_COLORS.get(s["strike_type"], TEAL_MED)
            line_fig.add_trace(go.Scatter(
                name=f"{s['strike_type']} ₹{s['strike']:,.0f}",
                x=xs, y=ys,
                mode="lines+markers",
                line=dict(color=color, width=2),
                marker=dict(size=5),
            ))

        # CMP reference line
        line_fig.add_vline(
            x=cmp_val, line_width=1, line_dash="dash",
            line_color="#9CA3AF",
            annotation_text=f"CMP ₹{cmp_val:,.0f}",
            annotation_position="top right",
            annotation_font_size=11,
        )
        # Zero P&L line
        line_fig.add_hline(
            y=0, line_width=1, line_dash="dot", line_color="#6B7280",
        )

        line_fig.update_layout(
            **_base_layout(height=280),
            title=dict(text="P&L at expiry", font=dict(size=14)),
            xaxis=dict(title="Stock price at expiry (₹)", showgrid=False,
                       zeroline=False),
            yaxis=dict(title="P&L (₹)", showgrid=True, gridcolor=GRID_COLOR,
                       zeroline=False),
        )
    else:
        # Placeholder line chart
        line_fig = go.Figure()
        for name, color in [("ITM", NAVY), ("ATM", BLUE_PRIMARY),
                             ("OTM+1", TEAL_MED), ("OTM+2", TEAL_LIGHT)]:
            line_fig.add_trace(go.Scatter(
                name=name, x=[], y=[], mode="lines+markers",
                line=dict(color=color, width=2),
            ))
        line_fig.update_layout(
            **_base_layout(height=280),
            title=dict(text="P&L at expiry (run Analyse to populate)",
                       font=dict(size=14)),
        )

    st.plotly_chart(line_fig, use_container_width=True,
                    config={"displayModeBar": False})
