"""
frontend/app.py — Breezy F&O covered call analyser UI.

Single-column layout with dark theme and top navigation.
"""

import os
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from jsx_report import generate_jsx
from nav import NAV_CSS, nav_bar

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# Dark-friendly chart colors
STRIKE_COLORS = {
    "ITM":   "#6A8FBF",
    "ATM":   "#58A6FF",
    "OTM+1": "#20A4A0",
    "OTM+2": "#39D0C8",
}
GRID_COLOR = "#30363D"

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Breezy F&O",
    page_icon="🤏",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("analyse")

# ── Brand header ──────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex; align-items:center; gap:14px; margin-bottom:8px;">
  <span style="font-size:44px; line-height:1;">🤏</span>
  <span style="font-size:36px; font-weight:900; color:#58A6FF;
               letter-spacing:-1px; font-family:'Segoe UI',Inter,sans-serif;">
    Breezy F&amp;O
  </span>
</div>
""", unsafe_allow_html=True)

# ── Backend health ────────────────────────────────────────────────────────────

try:
    h = requests.get(f"{BACKEND_URL}/health", timeout=5).json()
    if h.get("breeze_connected"):
        st.success("● Breeze connected")
    else:
        st.warning("⚠ Backend reachable — Breeze disconnected. Refresh session token.")
except Exception:
    st.error("✕ Backend unreachable")

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
        return "-"
    return f"₹{v:,.2f}"


def _base_layout(height=260):
    return dict(
        plot_bgcolor="#161B22",
        paper_bgcolor="#0D1117",
        margin=dict(l=8, r=8, t=40, b=36),
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#E6EDF3"),
        legend=dict(orientation="h", yanchor="bottom", y=1.05,
                    xanchor="left", x=0, font=dict(size=12)),
        height=height,
    )


# ── Input form ────────────────────────────────────────────────────────────────

st.divider()

sym_col, load_col = st.columns([4, 1])
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
        st.session_state.result = None
    except Exception as exc:
        st.error(f"Could not load expiries: {exc}")

expiry_date = None
if st.session_state.expiries:
    expiry_date = st.selectbox("Expiry date", options=st.session_state.expiries)
else:
    st.caption("Enter a symbol and press **Load ↓** to fetch expiry dates.")

already_holds = st.checkbox("I already hold this stock")

qty_held  = 0
avg_price = 0.0
if already_holds:
    q_col, p_col = st.columns(2)
    with q_col:
        qty_held = st.number_input("Shares held", min_value=0, step=1, value=250)
    with p_col:
        avg_price = st.number_input(
            "Avg purchase price (₹)", min_value=0.0, step=0.5, value=0.0,
            help="Leave 0 to use live CMP as cost basis.",
        )

with st.expander("Advanced: charges", expanded=False):
    brokerage = st.number_input("Brokerage per lot (₹)", min_value=1.0, step=1.0, value=40.0)
    stt_rate  = st.number_input("STT rate", min_value=0.0001, max_value=0.05,
                                 step=0.0001, value=0.001, format="%.4f")
    gst_rate  = st.number_input("GST rate", min_value=0.01, max_value=0.30,
                                 step=0.01, value=0.18, format="%.2f")

analyse_clicked = st.button("Analyse", use_container_width=True, disabled=(expiry_date is None))

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

# ── Results ───────────────────────────────────────────────────────────────────

res = st.session_state.result

if res:
    pos = res["position"]
    st.divider()

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("CMP",     _fmt_inr(res["cmp"]))
    mc2.metric("Lots",    pos["lots"])
    mc3.metric("Shares",  pos["shares"])
    mc4.metric("Capital", _fmt_inr(pos["total_cost"]))

    st.caption(
        f"Cost basis ₹{pos['cost_basis_per_share']:,.2f} · "
        f"Expiry {res['expiry_date']} · {res['days_to_expiry']} days · "
        f"Lot size {res['lot_size']}"
    )

    # Strike table
    rows = []
    for s in res["strikes"]:
        rows.append({
            "Strike type":       s["strike_type"],
            "Strike (₹)":        f"₹{s['strike']:,.0f}",
            "Premium (₹)":       f"₹{s['premium']:,.2f}",
            "Net premium":       _fmt_inr(s["net_premium_total"]),
            "Breakeven":         _fmt_inr(s["breakeven"]),
            "Max profit":        _fmt_inr(s["max_profit_total"]),
            "Yield %":           f"{s['premium_yield_pct']:.2f}%",
            "Ann. yield %":      (
                f"{s['annualised_yield_pct']:.1f}%"
                if s["annualised_yield_pct"] is not None else "-"
            ),
            "Downside protect.": f"{s['downside_protection_pct']:.2f}%",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=185)

    # ── Yield bar chart ───────────────────────────────────────────────────────
    strikes    = res["strikes"]
    bar_x      = [s["strike_type"] for s in strikes]
    bar_y_ann  = [s["annualised_yield_pct"] or 0 for s in strikes]
    bar_y_prem = [s["premium_yield_pct"] for s in strikes]
    bar_colors = [STRIKE_COLORS.get(t, "#20A4A0") for t in bar_x]

    bar_fig = go.Figure()
    bar_fig.add_trace(go.Bar(
        name="Ann. yield %", x=bar_x, y=bar_y_ann,
        marker_color=bar_colors,
        text=[f"{v:.1f}%" for v in bar_y_ann], textposition="outside",
    ))
    bar_fig.add_trace(go.Bar(
        name="Period yield %", x=bar_x, y=bar_y_prem,
        marker_color=["#39D0C8"] * len(bar_x),
        text=[f"{v:.2f}%" for v in bar_y_prem], textposition="outside",
    ))
    bar_fig.update_layout(
        **_base_layout(height=260),
        barmode="group",
        title=dict(text="Yield comparison by strike", font=dict(size=14)),
        yaxis=dict(title="Yield (%)", showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
    )
    st.plotly_chart(bar_fig, use_container_width=True, config={"displayModeBar": False})

    # ── P&L payoff chart ──────────────────────────────────────────────────────
    show_all = st.checkbox("Show all strikes on payoff chart", value=True)

    line_fig = go.Figure()
    for i, s in enumerate(strikes):
        if not show_all and i > 0:
            continue
        payoff = s["payoff"]
        xs = [p["price"] for p in payoff]
        ys = [p["pl"]    for p in payoff]
        line_fig.add_trace(go.Scatter(
            name=f"{s['strike_type']} ₹{s['strike']:,.0f}",
            x=xs, y=ys,
            mode="lines+markers",
            line=dict(color=STRIKE_COLORS.get(s["strike_type"], "#20A4A0"), width=2),
            marker=dict(size=5),
        ))

    line_fig.add_vline(
        x=res["cmp"], line_width=1, line_dash="dash", line_color="#8B949E",
        annotation_text=f"CMP ₹{res['cmp']:,.0f}",
        annotation_position="top right",
        annotation_font_size=11, annotation_font_color="#8B949E",
    )
    line_fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="#8B949E")
    line_fig.update_layout(
        **_base_layout(height=260),
        title=dict(text="P&L at expiry", font=dict(size=14)),
        xaxis=dict(title="Stock price at expiry (₹)", showgrid=False, zeroline=False,
                   gridcolor=GRID_COLOR),
        yaxis=dict(title="P&L (₹)", showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
    )
    st.plotly_chart(line_fig, use_container_width=True, config={"displayModeBar": False})

    # ── Download ──────────────────────────────────────────────────────────────
    try:
        jsx_bytes = generate_jsx([res], title=f"{res['symbol']} - Covered Call Report")
        st.download_button(
            label="Download JSX report",
            data=jsx_bytes,
            file_name=f"{res['symbol']}_covered_call.jsx",
            mime="text/plain",
        )
    except Exception as exc:
        st.warning(f"JSX report generation failed: {exc}")

else:
    placeholder = pd.DataFrame([
        {"Strike type": t, "Strike (₹)": "-", "Net premium": "-",
         "Breakeven": "-", "Max profit": "-", "Ann. yield %": "-",
         "Downside protect.": "-"}
        for t in ("ITM", "ATM", "OTM+1", "OTM+2")
    ])
    st.dataframe(placeholder, use_container_width=True, hide_index=True, height=185)
