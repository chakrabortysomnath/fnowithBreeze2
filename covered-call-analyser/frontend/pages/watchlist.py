"""
frontend/pages/watchlist.py — Multi-stock watchlist Streamlit page.

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

STRIKE_COLORS = {
    "ITM":   "#6A8FBF",
    "ATM":   "#58A6FF",
    "OTM+1": "#20A4A0",
    "OTM+2": "#39D0C8",
}
GRID_COLOR = "#30363D"

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Watchlist — Breezy F&O",
    page_icon="📋",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("watchlist")

# ── Brand header ──────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex; align-items:center; gap:12px; margin-bottom:8px;">
  <span style="font-size:36px; line-height:1;">📋</span>
  <span style="font-size:32px; font-weight:900; color:#58A6FF;
               letter-spacing:-1px; font-family:'Segoe UI',Inter,sans-serif;">
    Watchlist
  </span>
</div>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

for key, default in [
    ("wl_items",         []),
    ("wl_results",       []),
    ("wl_expiries_cache", {}),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Helpers ───────────────────────────────────────────────────────────────────

def _encode(sym: str) -> str:
    return sym.strip().upper().replace("&", "%26")


def _fetch_expiries(symbol: str) -> list[str]:
    cache = st.session_state.wl_expiries_cache
    if symbol in cache:
        return cache[symbol]
    r = requests.get(f"{BACKEND_URL}/expiries/{_encode(symbol)}", timeout=10)
    r.raise_for_status()
    expiries = r.json()["expiries"]
    cache[symbol] = expiries
    return expiries


def _run_watchlist() -> None:
    items = st.session_state.wl_items
    if not items:
        st.warning("Add at least one symbol before running.")
        return
    try:
        r = requests.post(
            f"{BACKEND_URL}/analyse-watchlist",
            json={"items": items},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            pass
        st.error(f"Request failed {exc.response.status_code}: {detail or exc}")
        return
    except Exception as exc:
        st.error(f"Request failed: {exc}")
        return

    results = data.get("results", [])
    successful = [r["result"] for r in results if r["status"] == "ok"]
    errors     = [(r["symbol"], r.get("error", "unknown"))
                  for r in results if r["status"] == "error"]

    st.session_state.wl_results = successful
    st.success(f"Done — {data.get('succeeded', len(successful))} succeeded, "
               f"{data.get('failed', len(errors))} failed.")
    for sym, err in errors:
        st.warning(f"⚠ {sym}: {err}")


def _atm_strike(res: dict) -> dict | None:
    for s in res.get("strikes", []):
        if s.get("strike_type") == "ATM":
            return s
    strikes = res.get("strikes", [])
    return strikes[0] if strikes else None


def _build_summary_df(results: list[dict]) -> pd.DataFrame:
    rows = []
    for res in results:
        atm = _atm_strike(res)
        if not atm:
            continue
        rows.append({
            "Symbol":       res["symbol"],
            "CMP (₹)":      f"₹{res['cmp']:,.2f}",
            "ATM Strike":   f"₹{atm['strike']:,.0f}",
            "Net Premium":  f"₹{atm['net_premium_total']:,.0f}",
            "Ann. Yield %": (
                f"{atm['annualised_yield_pct']:.1f}%"
                if atm.get("annualised_yield_pct") is not None else "-"
            ),
            "Breakeven":    f"₹{atm['breakeven']:,.2f}",
            "Max Profit":   f"₹{atm['max_profit_total']:,.0f}",
            "Expiry":       res["expiry_date"],
            "DTE":          res["days_to_expiry"],
        })
    return pd.DataFrame(rows)


def _base_layout(height=260):
    return dict(
        plot_bgcolor="#161B22",
        paper_bgcolor="#0D1117",
        margin=dict(l=8, r=8, t=40, b=36),
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#E6EDF3"),
        legend=dict(orientation="h", yanchor="bottom", y=1.05,
                    xanchor="left", x=0, font=dict(size=11)),
        height=height,
    )


# ── Add symbol form ───────────────────────────────────────────────────────────

st.divider()
st.markdown('<div class="section-hd">Add to watchlist</div>', unsafe_allow_html=True)

sym_col, add_col = st.columns([4, 1])
with sym_col:
    new_symbol = st.text_input(
        "symbol", value="", placeholder="e.g. INFY",
        label_visibility="collapsed",
    )

new_expiry = None
if new_symbol.strip():
    sym_upper = new_symbol.strip().upper()
    try:
        exp_list   = _fetch_expiries(sym_upper)
        new_expiry = st.selectbox("Expiry", options=exp_list,
                                  key=f"wl_exp_{sym_upper}")
    except Exception as exc:
        st.caption(f"Could not load expiries: {exc}")

already_holds = st.checkbox("Already holds", key="wl_already_holds")
qty_held  = 0
avg_price = 0.0
if already_holds:
    qc, pc = st.columns(2)
    with qc:
        qty_held  = st.number_input("Qty held", min_value=0, step=1,
                                     value=0, key="wl_qty")
    with pc:
        avg_price = st.number_input("Avg price (₹)", min_value=0.0, step=0.5,
                                     value=0.0, key="wl_avg")

with add_col:
    st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
    add_clicked = st.button("+ Add", use_container_width=True,
                            disabled=(not new_symbol.strip() or new_expiry is None))

if add_clicked and new_symbol.strip() and new_expiry:
    sym_upper = new_symbol.strip().upper()
    existing  = [(i["symbol"], i["expiry_date"]) for i in st.session_state.wl_items]
    if (sym_upper, new_expiry) in existing:
        st.warning(f"{sym_upper} {new_expiry} is already in the watchlist.")
    else:
        st.session_state.wl_items.append({
            "symbol":             sym_upper,
            "expiry_date":        new_expiry,
            "already_holds":      already_holds,
            "quantity_held":      qty_held,
            "avg_purchase_price": avg_price,
        })
        st.rerun()

# ── Watchlist queue ───────────────────────────────────────────────────────────

st.markdown('<div class="section-hd">Watchlist</div>', unsafe_allow_html=True)

if not st.session_state.wl_items:
    st.caption("No symbols added yet.")
else:
    to_remove = None
    for idx, item in enumerate(st.session_state.wl_items):
        cols = st.columns([3, 3, 1])
        cols[0].write(f"**{item['symbol']}**")
        cols[1].write(item["expiry_date"])
        if cols[2].button("✕", key=f"rm_{idx}"):
            to_remove = idx
    if to_remove is not None:
        st.session_state.wl_items.pop(to_remove)
        st.rerun()

st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
if st.button("Run All ▶", use_container_width=True,
             disabled=len(st.session_state.wl_items) == 0):
    with st.spinner("Analysing watchlist…"):
        _run_watchlist()

# ── Summary results ───────────────────────────────────────────────────────────

if st.session_state.wl_results:
    st.divider()
    st.markdown('<div class="section-hd">Summary (ATM strike)</div>',
                unsafe_allow_html=True)

    summary_df = _build_summary_df(st.session_state.wl_results)
    if not summary_df.empty:
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

    try:
        jsx_bytes = generate_jsx(
            st.session_state.wl_results,
            title="Breezy F&O - Watchlist Report",
        )
        st.download_button(
            label="Download JSX report",
            data=jsx_bytes,
            file_name="watchlist_report.jsx",
            mime="text/plain",
        )
    except Exception as exc:
        st.warning(f"JSX report generation failed: {exc}")

    # ── Detail view ───────────────────────────────────────────────────────────
    st.divider()
    st.markdown('<div class="section-hd">Strike detail</div>', unsafe_allow_html=True)

    symbol_options = [r["symbol"] for r in st.session_state.wl_results]
    selected = st.selectbox("Select symbol to expand", options=symbol_options)
    res = next((r for r in st.session_state.wl_results if r["symbol"] == selected), None)

    if res:
        pos = res["position"]
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("CMP",     f"₹{res['cmp']:,.2f}")
        mc2.metric("Lots",    pos["lots"])
        mc3.metric("Shares",  pos["shares"])
        mc4.metric("Capital", f"₹{pos['total_cost']:,.0f}")

        st.caption(
            f"Cost basis ₹{pos['cost_basis_per_share']:,.2f} · "
            f"Expiry {res['expiry_date']} · {res['days_to_expiry']} days · "
            f"Lot size {res['lot_size']}"
        )

        rows = []
        for s in res["strikes"]:
            rows.append({
                "Type":         s["strike_type"],
                "Strike (₹)":   f"₹{s['strike']:,.0f}",
                "Net Prem (₹)": f"₹{s['net_premium_total']:,.0f}",
                "Breakeven":    f"₹{s['breakeven']:,.2f}",
                "Max Profit":   f"₹{s['max_profit_total']:,.0f}",
                "Yield %":      f"{s['premium_yield_pct']:.2f}%",
                "Ann. Yield %": (
                    f"{s['annualised_yield_pct']:.1f}%"
                    if s.get("annualised_yield_pct") is not None else "-"
                ),
                "Downside %":   f"{s['downside_protection_pct']:.2f}%",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True, height=180)

        line_fig = go.Figure()
        for s in res["strikes"]:
            payoff = s["payoff"]
            xs = [p["price"] for p in payoff]
            ys = [p["pl"]    for p in payoff]
            line_fig.add_trace(go.Scatter(
                name=f"{s['strike_type']} ₹{s['strike']:,.0f}",
                x=xs, y=ys,
                mode="lines+markers",
                line=dict(color=STRIKE_COLORS.get(s["strike_type"], "#20A4A0"), width=2),
                marker=dict(size=4),
            ))
        line_fig.add_vline(
            x=res["cmp"], line_width=1, line_dash="dash", line_color="#8B949E",
            annotation_text=f"CMP ₹{res['cmp']:,.0f}",
            annotation_position="top right",
            annotation_font_size=11, annotation_font_color="#8B949E",
        )
        line_fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="#8B949E")
        line_fig.update_layout(
            **_base_layout(height=280),
            title=dict(text=f"P&L at expiry — {selected}", font=dict(size=14)),
            xaxis=dict(title="Stock price at expiry (₹)", showgrid=False,
                       zeroline=False, gridcolor=GRID_COLOR),
            yaxis=dict(title="P&L (₹)", showgrid=True,
                       gridcolor=GRID_COLOR, zeroline=False),
        )
        st.plotly_chart(line_fig, use_container_width=True,
                        config={"displayModeBar": False})
else:
    st.info("Add symbols to your watchlist and click **Run All ▶** to see results here.")
