"""
frontend/pages/compare.py — Instrument comparison tab for Breezy F&O.

Allows the user to select 2–5 NSE F&O instruments and run a side-by-side
covered call analysis using the existing backend analysis engine.
No Claude API calls are made — pure Python / backend analysis only.
"""

import io
import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from nav import NAV_CSS, nav_bar

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

STRIKE_COLORS = {
    "ITM":   "#6A8FBF",
    "ATM":   "#58A6FF",
    "OTM+1": "#20A4A0",
    "OTM+2": "#39D0C8",
}
GRID_COLOR = "#30363D"
MAX_INSTRUMENTS = 5

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Compare — Breezy F&O",
    page_icon="⚖️",
    layout="wide",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("compare")

# ── Brand header ──────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
  <span style="font-size:36px; line-height:1;">⚖️</span>
  <span style="font-size:32px; font-weight:900; color:#58A6FF;
               letter-spacing:-1px; font-family:'Segoe UI',Inter,sans-serif;">
    Instrument Comparison
  </span>
</div>
<p style="color:#8B949E; font-size:13px; margin-bottom:18px;">
  Select 2–5 F&amp;O instruments to compare covered call metrics side-by-side.
  Analysis uses the nearest expiry for each instrument. No AI API calls — pure Python.
</p>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _encode(sym: str) -> str:
    return sym.strip().upper().replace("&", "%26")


@st.cache_data(ttl=300)
def _fetch_symbols() -> list[str]:
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", timeout=5)
        r.raise_for_status()
        return sorted(r.json()["lot_sizes"].keys())
    except Exception:
        return []


def _fetch_nearest_expiry(symbol: str) -> str | None:
    """Return the nearest available expiry date for the symbol."""
    try:
        r = requests.get(f"{BACKEND_URL}/expiries/{_encode(symbol)}", timeout=10)
        r.raise_for_status()
        expiries = r.json().get("expiries", [])
        return expiries[0] if expiries else None
    except Exception:
        return None


def _get_strike(res: dict, strike_type: str) -> dict | None:
    """Return strike data for the given strike_type from an analysis result."""
    for s in res.get("strikes", []):
        if s.get("strike_type") == strike_type:
            return s
    # Fallback: return ATM if requested type not available
    for s in res.get("strikes", []):
        if s.get("strike_type") == "ATM":
            return s
    strikes = res.get("strikes", [])
    return strikes[0] if strikes else None


def _fmt_inr(v) -> str:
    if v is None:
        return "—"
    return f"₹{v:,.2f}"


def _fmt_pct(v, decimals=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _fmt_int(v) -> str:
    if v is None:
        return "—"
    return f"{v:,}"


def _base_layout(height=300):
    return dict(
        plot_bgcolor="#161B22",
        paper_bgcolor="#0D1117",
        margin=dict(l=8, r=8, t=44, b=36),
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#E6EDF3"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, font=dict(size=11)),
        height=height,
    )


# ── Session state ─────────────────────────────────────────────────────────────

if "cmp_results" not in st.session_state:
    st.session_state.cmp_results = []
if "cmp_strike_view" not in st.session_state:
    st.session_state.cmp_strike_view = "ATM"

# ── Instrument selection ──────────────────────────────────────────────────────

st.divider()
st.markdown('<div class="section-hd">Select Instruments</div>', unsafe_allow_html=True)

symbols = _fetch_symbols()

selected_symbols = st.multiselect(
    "Instruments (2–5)",
    options=symbols if symbols else [],
    max_selections=MAX_INSTRUMENTS,
    placeholder="Search and select NSE F&O symbols…",
    label_visibility="collapsed",
    key="cmp_symbols",
)

if len(selected_symbols) == 1:
    st.info("Select at least 2 instruments to compare.")
elif len(selected_symbols) > MAX_INSTRUMENTS:
    st.warning(f"Maximum {MAX_INSTRUMENTS} instruments allowed.")

# ── Charges configuration (optional) ─────────────────────────────────────────

with st.expander("⚙️ Configure Charges (optional)", expanded=False):
    ch1, ch2, ch3 = st.columns(3)
    with ch1:
        brokerage = st.number_input(
            "Brokerage / lot (₹)", min_value=1.0, step=1.0, value=40.0, key="cmp_brok"
        )
    with ch2:
        stt_rate = st.number_input(
            "STT rate", min_value=0.0001, max_value=0.05,
            step=0.0001, value=0.001, format="%.4f", key="cmp_stt"
        )
    with ch3:
        gst_rate = st.number_input(
            "GST rate", min_value=0.01, max_value=0.30,
            step=0.01, value=0.18, format="%.2f", key="cmp_gst"
        )

# ── Run comparison ────────────────────────────────────────────────────────────

st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

run_disabled = len(selected_symbols) < 2
run_clicked  = st.button(
    "Run Comparison ▶",
    use_container_width=True,
    disabled=run_disabled,
    key="cmp_run",
)

if run_clicked and len(selected_symbols) >= 2:
    results_ok   = []
    results_err  = []

    with st.status("Running comparative analysis…", expanded=True) as status:
        st.write(f"🔍 Resolving nearest expiries for {len(selected_symbols)} instrument(s)…")

        items = []
        for sym in selected_symbols:
            expiry = _fetch_nearest_expiry(sym)
            if expiry is None:
                st.write(f"  ⚠️ {sym}: could not fetch expiry — skipping")
                results_err.append((sym, "Could not fetch expiry date"))
                continue
            items.append({
                "symbol":             sym,
                "expiry_date":        expiry,
                "already_holds":      False,
                "quantity_held":      0,
                "avg_purchase_price": 0.0,
                "brokerage":          brokerage,
                "stt_rate":           stt_rate,
                "gst_rate":           gst_rate,
            })
            st.write(f"  ✓ {sym} → expiry {expiry}")

        if not items:
            status.update(label="No valid instruments to analyse.", state="error")
            st.stop()

        n = len(items)
        st.write(f"📡 Connecting to market data — {n} instrument(s) queued…")
        st.write("⚙️ Running covered call calculations (ITM, ATM, OTM+1, OTM+2) for each…")
        st.write("  This may take 10–30 seconds depending on market data availability.")

        try:
            r = requests.post(
                f"{BACKEND_URL}/compare",
                json={"items": items},
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
        except requests.HTTPError as exc:
            detail = ""
            try:
                detail = exc.response.json().get("detail", "")
            except Exception:
                pass
            status.update(label="Analysis failed.", state="error")
            st.error(f"Backend error {exc.response.status_code}: {detail or exc}")
            st.stop()
        except Exception as exc:
            status.update(label="Analysis failed.", state="error")
            st.error(f"Request failed: {exc}")
            st.stop()

        for item_result in data.get("results", []):
            if item_result["status"] == "ok":
                results_ok.append(item_result["result"])
            else:
                results_err.append((item_result["symbol"], item_result.get("error", "unknown")))

        succeeded = data.get("succeeded", len(results_ok))
        failed    = data.get("failed", len(results_err))

        st.write(f"✅ Analysis complete — {succeeded} succeeded, {failed} failed.")
        for sym, err in results_err:
            st.write(f"  ⚠️ {sym}: {err}")

        if not results_ok:
            status.update(label="No instruments analysed successfully.", state="error")
            st.stop()

        status.update(
            label=f"Comparison ready — {succeeded} instrument(s) analysed.",
            state="complete",
        )

    st.session_state.cmp_results = results_ok

# Show errors from failed instruments (even without re-running)
for sym, err in ([] if run_clicked else []):
    st.warning(f"⚠ {sym}: {err}")

# ── Results section ───────────────────────────────────────────────────────────

if st.session_state.cmp_results:
    results = st.session_state.cmp_results
    st.divider()

    # Strike type selector
    col_sel, col_info = st.columns([3, 5])
    with col_sel:
        strike_view = st.radio(
            "Strike view",
            options=["ITM", "ATM", "OTM+1", "OTM+2"],
            index=1,
            horizontal=True,
            key="cmp_strike_radio",
        )
    with col_info:
        st.markdown(
            f"<p style='color:#8B949E; font-size:13px; margin-top:8px;'>"
            f"Showing <b style='color:#58A6FF'>{strike_view}</b> strike for each instrument. "
            f"Falls back to ATM if selected strike is unavailable.</p>",
            unsafe_allow_html=True,
        )

    # Build comparison data
    symbols_ok = [r["symbol"] for r in results]

    rows: dict[str, list] = {}

    def _add_row(label, values):
        rows[label] = values

    _add_row("📈 CMP (₹)",            [_fmt_inr(r["cmp"]) for r in results])
    _add_row("📅 Expiry",              [r["expiry_date"] for r in results])
    _add_row("⏳ DTE (days)",           [str(r["days_to_expiry"]) for r in results])
    _add_row("📦 Lot Size",            [f"{r['lot_size']:,}" for r in results])

    strikes = [_get_strike(r, strike_view) for r in results]

    _add_row("🎯 Strike (₹)",          [_fmt_inr(s["strike"]) if s else "—" for s in strikes])
    _add_row("🏷️ Strike Type",         [s.get("strike_type", "—") if s else "—" for s in strikes])

    # ── Performance ──
    _add_row("— PERFORMANCE —",        [""] * len(results))
    _add_row("Gross Premium (₹)",      [_fmt_inr(s["gross_premium_total"]) if s else "—" for s in strikes])
    _add_row("Net Premium / Share (₹)",[_fmt_inr(s["net_premium_per_share"]) if s else "—" for s in strikes])
    _add_row("Net Premium Total (₹)",  [_fmt_inr(s["net_premium_total"]) if s else "—" for s in strikes])
    _add_row("Premium Yield %",        [_fmt_pct(s["premium_yield_pct"]) if s else "—" for s in strikes])
    _add_row("★ Annualised Yield %",   [
        _fmt_pct(s["annualised_yield_pct"], 1) if s and s.get("annualised_yield_pct") is not None else "—"
        for s in strikes
    ])

    # ── Risk ──
    _add_row("— RISK —",               [""] * len(results))
    _add_row("Breakeven (₹)",          [_fmt_inr(s["breakeven"]) if s else "—" for s in strikes])
    _add_row("Breakeven % below CMP",  [_fmt_pct(s["breakeven_pct_below_cmp"]) if s else "—" for s in strikes])
    _add_row("★ Downside Protection %",[_fmt_pct(s["downside_protection_pct"]) if s else "—" for s in strikes])
    _add_row("Implied Volatility %",   [
        _fmt_pct(s["iv"], 1) if s and s.get("iv") is not None else "—"
        for s in strikes
    ])

    # ── Reward ──
    _add_row("— REWARD —",             [""] * len(results))
    _add_row("Max Profit / Share (₹)", [_fmt_inr(s["max_profit_per_share"]) if s else "—" for s in strikes])
    _add_row("★ Max Profit Total (₹)", [_fmt_inr(s["max_profit_total"]) if s else "—" for s in strikes])

    # ── Position ──
    _add_row("— POSITION —",           [""] * len(results))
    _add_row("Lots",                   [str(r["position"]["lots"]) for r in results])
    _add_row("Shares",                 [f"{r['position']['shares']:,}" for r in results])
    _add_row("Capital Deployed (₹)",   [_fmt_inr(r["position"]["total_cost"]) for r in results])
    _add_row("Cost Basis / Share (₹)", [_fmt_inr(r["position"]["cost_basis_per_share"]) for r in results])

    # ── Charges ──
    _add_row("— CHARGES —",            [""] * len(results))
    _add_row("Total Charges (₹)",      [_fmt_inr(s["charges"]["total"]) if s else "—" for s in strikes])
    _add_row("STT (₹)",                [_fmt_inr(s["charges"]["stt"]) if s else "—" for s in strikes])
    _add_row("Brokerage (₹)",          [_fmt_inr(s["charges"]["brokerage"]) if s else "—" for s in strikes])
    _add_row("GST (₹)",                [_fmt_inr(s["charges"]["gst"]) if s else "—" for s in strikes])

    # ── Liquidity ──
    _add_row("— LIQUIDITY —",          [""] * len(results))
    _add_row("Open Interest",          [
        _fmt_int(s.get("open_interest")) if s else "—" for s in strikes
    ])
    _add_row("Volume",                 [
        _fmt_int(s.get("volume")) if s else "—" for s in strikes
    ])

    # Build and display the comparison DataFrame
    st.markdown(
        f'<div class="section-hd">📊 Comparison Table — {strike_view} Strike</div>',
        unsafe_allow_html=True,
    )

    comp_df = pd.DataFrame(rows, index=symbols_ok).T
    comp_df.index.name = "Metric"

    # Style section headers
    def _style_rows(df):
        styles = []
        for idx in df.index:
            if idx.startswith("—") or idx.startswith("★"):
                styles.append([
                    "background-color: #161B22; color: #58A6FF; font-weight: 700;"
                ] * len(df.columns))
            else:
                styles.append([""] * len(df.columns))
        return pd.DataFrame(styles, index=df.index, columns=df.columns)

    styled = comp_df.style.apply(_style_rows, axis=None)
    st.dataframe(styled, use_container_width=True, height=min(38 * len(comp_df) + 38, 900))

    # CSV export
    csv_buf = io.StringIO()
    comp_df.to_csv(csv_buf)
    st.download_button(
        label="⬇ Download Comparison CSV",
        data=csv_buf.getvalue().encode("utf-8"),
        file_name=f"breezy_compare_{strike_view}.csv",
        mime="text/csv",
    )

    # ── P&L Payoff chart ─────────────────────────────────────────────────────

    st.divider()
    st.markdown('<div class="section-hd">📉 P&L at Expiry — ATM Strikes</div>', unsafe_allow_html=True)
    st.caption("P&L curves shown for the ATM strike of each instrument for a fair cross-instrument comparison.")

    line_colors = ["#58A6FF", "#20A4A0", "#FF7B7B", "#FFD166", "#39D0C8"]
    payoff_fig  = go.Figure()

    for i, res in enumerate(results):
        atm = _get_strike(res, "ATM")
        if not atm or not atm.get("payoff"):
            continue
        xs = [p["price"] for p in atm["payoff"]]
        ys = [p["pl"]    for p in atm["payoff"]]
        payoff_fig.add_trace(go.Scatter(
            name=f"{res['symbol']} (₹{atm['strike']:,.0f})",
            x=xs, y=ys,
            mode="lines+markers",
            line=dict(color=line_colors[i % len(line_colors)], width=2),
            marker=dict(size=4),
        ))

    payoff_fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="#8B949E")
    payoff_fig.update_layout(
        **_base_layout(height=320),
        title=dict(text="P&L at Expiry (ATM Strike)", font=dict(size=14)),
        xaxis=dict(title="Stock price at expiry (₹)", showgrid=False, zeroline=False),
        yaxis=dict(title="P&L (₹)", showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
    )
    st.plotly_chart(payoff_fig, use_container_width=True, config={"displayModeBar": False})

    # ── Per-instrument strike detail ──────────────────────────────────────────

    st.divider()
    st.markdown('<div class="section-hd">🔍 Strike Detail per Instrument</div>', unsafe_allow_html=True)

    for res in results:
        with st.expander(f"{res['symbol']} — all strikes", expanded=False):
            p  = res["position"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("CMP",     f"₹{res['cmp']:,.2f}")
            m2.metric("Lots",    p["lots"])
            m3.metric("Shares",  f"{p['shares']:,}")
            m4.metric("Capital", f"₹{p['total_cost']:,.0f}")

            st.caption(
                f"Expiry {res['expiry_date']} · {res['days_to_expiry']} days · "
                f"Lot size {res['lot_size']:,} · "
                f"Cost basis ₹{p['cost_basis_per_share']:,.2f}"
            )

            strike_rows = []
            for s in res["strikes"]:
                strike_rows.append({
                    "Type":            s["strike_type"],
                    "Strike (₹)":      f"₹{s['strike']:,.0f}",
                    "Premium (₹)":     f"₹{s['premium']:,.2f}",
                    "Net Prem (₹)":    f"₹{s['net_premium_total']:,.0f}",
                    "Ann. Yield %":    (
                        f"{s['annualised_yield_pct']:.1f}%"
                        if s.get("annualised_yield_pct") is not None else "—"
                    ),
                    "Breakeven (₹)":   f"₹{s['breakeven']:,.2f}",
                    "Downside %":      f"{s['downside_protection_pct']:.2f}%",
                    "Max Profit (₹)":  f"₹{s['max_profit_total']:,.0f}",
                    "IV %":            f"{s['iv']:.1f}%" if s.get("iv") else "—",
                    "OI":              f"{s['open_interest']:,}" if s.get("open_interest") else "—",
                })
            st.dataframe(
                pd.DataFrame(strike_rows),
                use_container_width=True,
                hide_index=True,
                height=180,
            )

else:
    st.markdown(
        "<p style='color:#8B949E; font-size:14px;'>"
        "Select 2–5 instruments above and click <b>Run Comparison ▶</b> to see results here."
        "</p>",
        unsafe_allow_html=True,
    )
