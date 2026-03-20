"""
frontend/pages/compare.py — Instrument comparison tab for Breezy F&O.

Allows the user to select 2–5 NSE F&O instruments and run a side-by-side
covered call analysis using the existing backend analysis engine.
No Claude API calls are made — pure Python / backend analysis only.
"""

import io
import math as _math
import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from auth import check_auth
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

check_auth()

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


def _bs_call_price(S, K, T, r, sigma):
    if sigma <= 0 or T <= 0:
        return max(S - K * _math.exp(-r * T), 0.0)
    d1 = (_math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * _math.sqrt(T))
    d2 = d1 - sigma * _math.sqrt(T)
    N  = lambda x: 0.5 * (1.0 + _math.erf(x / _math.sqrt(2.0)))
    return S * N(d1) - K * _math.exp(-r * T) * N(d2)


def _bs_iv(S, K, T_days, C, r=0.065):
    if T_days <= 0 or C <= 0 or S <= 0 or K <= 0:
        return None
    T = T_days / 365.0
    lo, hi = 0.001, 5.0
    intrinsic = max(S - K * _math.exp(-r * T), 0.0)
    if C <= intrinsic:
        return None
    for _ in range(120):
        mid   = (lo + hi) / 2.0
        price = _bs_call_price(S, K, T, r, mid)
        if abs(price - C) < 0.01:
            return round(mid * 100, 1)
        lo, hi = (mid, hi) if price < C else (lo, mid)
    return round(((lo + hi) / 2.0) * 100, 1)


def _bs_greeks(S, K, T_days, sigma_pct, ltp_per_share, r=0.065):
    T = T_days / 365.0
    sigma = sigma_pct / 100.0
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    try:
        d1 = (_math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * _math.sqrt(T))
        d2 = d1 - sigma * _math.sqrt(T)
        N  = lambda x: 0.5 * (1.0 + _math.erf(x / _math.sqrt(2.0)))
        Np = lambda x: _math.exp(-0.5 * x * x) / _math.sqrt(2.0 * _math.pi)
        KerT = K * _math.exp(-r * T)
        delta = N(d1)
        gamma = Np(d1) / (S * sigma * _math.sqrt(T))
        theta_seller = (S * Np(d1) * sigma / (2.0 * _math.sqrt(T)) + r * KerT * N(d2)) / 365.0
        vega  = S * Np(d1) * _math.sqrt(T) / 100.0
        rho   = KerT * T * N(d2) / 100.0
        implied_put = max(ltp_per_share + KerT - S, 0.0)
        intrinsic   = max(S - K, 0.0)
        time_value  = ltp_per_share - intrinsic
        return {
            "delta": round(delta, 4), "gamma": round(gamma, 6),
            "theta_per_day": round(theta_seller, 4), "vega": round(vega, 4),
            "rho": round(rho, 4), "implied_put": round(implied_put, 2),
            "intrinsic": round(intrinsic, 2), "time_value": round(time_value, 2),
        }
    except Exception:
        return None


def _cmp_table_html(results: list[dict], strike_view: str, greeks_by_sym: dict) -> str:
    """Comparison table: rows = metric groups, columns = symbols.

    Each column shows the selected strike_view for that symbol.
    greeks_by_sym: {symbol: greeks_dict or None}
    """
    symbols = [r["symbol"] for r in results]
    strikes = {r["symbol"]: _get_strike(r, strike_view) for r in results}

    hd = ("padding:8px 10px;border-bottom:2px solid #30363D;"
          "color:#8B949E;font-size:11px;font-weight:600;white-space:nowrap;")
    td = ("padding:6px 10px;border-bottom:1px solid #21262D;"
          "color:#C9D1D9;font-size:12px;text-align:right;"
          "font-family:'Courier New',monospace;white-space:nowrap;")
    mtd = ("padding:6px 10px;border-bottom:1px solid #21262D;"
           "color:#E6EDF3;font-size:12px;text-align:left;")
    shd = ("padding:5px 10px;background:#161B22;"
           "color:#58A6FF;font-size:11px;font-weight:700;letter-spacing:0.5px;")
    ncols = len(symbols) + 1

    def _fmt(v, fmt):
        if v is None: return "—"
        try:
            if fmt == "inr":    return f"₹{v:,.2f}"
            if fmt == "inr0":   return f"₹{v:,.0f}"
            if fmt == "pct1":   return f"{v:.1f}%"
            if fmt == "pct2":   return f"{v:.2f}%"
            if fmt == "spct1":  return f"{v:+.1f}%"
            if fmt == "int":    return f"{v:,}"
            if fmt == "f4":     return f"{v:.4f}"
            if fmt == "f6":     return f"{v:.6f}"
            return str(v)
        except Exception: return "—"

    def sec(title):
        return f'<tr><td colspan="{ncols}" style="{shd}">{title}</td></tr>'

    def row(metric, tip, vals_by_sym, fmt):
        tip_a = f' title="{tip}"' if tip else ""
        icon  = (' <span style="color:#8B949E;font-size:10px;cursor:help;">ⓘ</span>'
                 if tip else "")
        r = f'<tr><td style="{mtd}"{tip_a}>{metric}{icon}</td>'
        for sym in symbols:
            r += f'<td style="{td}">{_fmt(vals_by_sym.get(sym), fmt)}</td>'
        return r + "</tr>"

    def sv(sym, key, subkey=None):
        s = strikes.get(sym)
        if s is None: return None
        v = s.get(key)
        if subkey is not None:
            return v.get(subkey) if isinstance(v, dict) else None
        return v

    def gv(sym, key):
        g = greeks_by_sym.get(sym)
        return g.get(key) if g else None

    out = [
        '<div style="overflow-x:auto;">',
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:Inter,\'Segoe UI\',sans-serif;">',
        '<thead><tr>',
        f'<th style="{hd} text-align:left;min-width:160px;">Metric</th>',
    ]
    for r in results:
        s   = strikes.get(r["symbol"])
        stk = f" ₹{s['strike']:,.0f}" if s else ""
        out.append(
            f'<th style="{hd} text-align:right;">'
            f'<span style="color:#58A6FF;font-weight:700;">{r["symbol"]}</span><br>'
            f'<span style="color:#E6EDF3;font-size:12px;">{strike_view}{stk}</span>'
            f'</th>'
        )
    out.append('</tr></thead><tbody>')

    # Position
    out.append(sec("── POSITION ──"))
    out.append(row("CMP (₹)", "Live last traded price", {r["symbol"]: r["cmp"] for r in results}, "inr"))
    out.append(row("Expiry",  "Option expiry date", {r["symbol"]: r["expiry_date"] for r in results}, ""))
    out.append(row("DTE",     "Days to expiry", {r["symbol"]: r["days_to_expiry"] for r in results}, "int"))
    out.append(row("Lot Size","Shares per F&O contract", {r["symbol"]: r["lot_size"] for r in results}, "int"))
    out.append(row("Capital Deployed (₹)", "Total capital at cost basis × shares",
                   {r["symbol"]: r["position"]["total_cost"] for r in results}, "inr"))
    out.append(row("Cost Basis / Share (₹)", "Purchase price per share",
                   {r["symbol"]: r["position"]["cost_basis_per_share"] for r in results}, "inr"))

    # Strikes
    out.append(sec("── STRIKES ──"))
    out.append(row("Strike (₹)",         "", {sym: sv(sym, "strike") for sym in symbols}, "inr0"))
    out.append(row("Moneyness %",         "(Strike − CMP) / CMP × 100",
                   {sym: (sv(sym, "strike") - r["cmp"]) / r["cmp"] * 100
                    if sv(sym, "strike") and r.get("cmp") else None
                    for sym, r in zip(symbols, results)}, "spct1"))
    out.append(row("Intrinsic Value (₹/sh)", "max(CMP − Strike, 0)",
                   {sym: max(r["cmp"] - sv(sym, "strike"), 0.0)
                    if sv(sym, "strike") and r.get("cmp") else None
                    for sym, r in zip(symbols, results)}, "inr"))
    out.append(row("Time Value (₹/sh)",   "LTP − Intrinsic Value",
                   {sym: gv(sym, "time_value") for sym in symbols}, "inr"))

    # Premium & Income
    out.append(sec("── PREMIUM & INCOME ──"))
    out.append(row("Gross Premium LTP (₹/sh)", "Option LTP per share",
                   {sym: sv(sym, "premium") for sym in symbols}, "inr"))
    out.append(row("Net Premium / Share (₹)", "After all charges",
                   {sym: sv(sym, "net_premium_per_share") for sym in symbols}, "inr"))
    out.append(row("Net Premium Total (₹)", "Full lot net premium",
                   {sym: sv(sym, "net_premium_total") for sym in symbols}, "inr"))
    out.append(row("Charges Total (₹)", "STT + Brokerage + GST",
                   {sym: sv(sym, "charges", "total") for sym in symbols}, "inr"))
    out.append(row("Charges %", "Charges as % of gross premium",
                   {sym: (sv(sym, "charges", "total") / sv(sym, "gross_premium_total") * 100
                          if sv(sym, "gross_premium_total") else None) for sym in symbols}, "pct1"))

    # Market Data
    out.append(sec("── MARKET DATA ──"))
    out.append(row("IV %",           "Implied Volatility (from chain or BS-computed)",
                   {sym: sv(sym, "_iv_enriched") or sv(sym, "iv") for sym in symbols}, "pct1"))
    out.append(row("Open Interest",  "Outstanding contracts — liquidity proxy",
                   {sym: sv(sym, "open_interest") for sym in symbols}, "int"))
    out.append(row("Volume",         "Today's traded contracts",
                   {sym: sv(sym, "volume") for sym in symbols}, "int"))

    # Performance
    out.append(sec("── PERFORMANCE ──"))
    out.append(row("Breakeven (₹)",          "Stock price at P&L=0",
                   {sym: sv(sym, "breakeven") for sym in symbols}, "inr0"))
    out.append(row("Downside Protection %",   "(CMP − Breakeven) / CMP",
                   {sym: sv(sym, "downside_protection_pct") for sym in symbols}, "pct2"))
    out.append(row("Premium Yield %",         "Net premium / capital deployed",
                   {sym: sv(sym, "premium_yield_pct") for sym in symbols}, "pct2"))
    out.append(row("★ Annualised Yield %",    "Yield scaled to 365 days",
                   {sym: sv(sym, "annualised_yield_pct") for sym in symbols}, "pct1"))
    out.append(row("★ Max Profit Total (₹)",  "Best-case P&L if called away at strike",
                   {sym: sv(sym, "max_profit_total") for sym in symbols}, "inr"))

    # Greeks
    out.append(sec("── GREEKS (Black-Scholes, r = 6.5%) ──"))
    out.append(
        f'<tr><td colspan="{ncols}" style="padding:3px 10px 5px;'
        f'color:#8B949E;font-size:11px;font-style:italic;">'
        f'Computed using IV from chain data or Black-Scholes inversion. '
        f'Θ = seller perspective (positive favourable). Vega = loss per +1% IV.'
        f'</td></tr>'
    )
    out.append(row("Δ Delta",              "N(d1) call delta",
                   {sym: gv(sym, "delta") for sym in symbols}, "f4"))
    out.append(row("Γ Gamma",              "Delta change per ₹1 CMP move",
                   {sym: gv(sym, "gamma") for sym in symbols}, "f6"))
    out.append(row("Θ Theta/day (₹/sh)",   "Daily time decay benefit (seller)",
                   {sym: gv(sym, "theta_per_day") for sym in symbols}, "inr"))
    out.append(row("V Vega/+1% IV (₹/sh)", "₹ loss per +1% IV rise (seller is short vega)",
                   {sym: gv(sym, "vega") for sym in symbols}, "inr"))
    out.append(row("ρ Rho/+1% rate (₹/sh)","₹ change per +1% risk-free rate",
                   {sym: gv(sym, "rho") for sym in symbols}, "inr"))

    # Put-Call Summary
    out.append(sec("── PUT-CALL SUMMARY ──"))
    out.append(row("Implied Put Price (₹/sh)", "From Put-Call Parity: P = C + K·e^(−rT) − S",
                   {sym: gv(sym, "implied_put") for sym in symbols}, "inr"))
    out.append(row("Put Delta (approx.)",      "Δ − 1 (from parity)",
                   {sym: ((gv(sym, "delta") or 0) - 1.0) if gv(sym, "delta") is not None else None
                    for sym in symbols}, "f4"))

    out.append('</tbody></table></div>')
    return "".join(out)


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
        STRIKE_TIPS = {
            "ITM":   "Strike below CMP — higher premium, most protection, upside capped.",
            "ATM":   "Strike nearest to CMP — balanced premium vs upside, maximum time value.",
            "OTM+1": "One strike above CMP — lower premium, participates in modest upside.",
            "OTM+2": "Two strikes above CMP — lowest premium, maximum upside participation.",
        }
        st.markdown(
            f"<p style='color:#8B949E; font-size:13px; margin-top:8px;'>"
            f"<b style='color:#58A6FF'>{strike_view}</b> — {STRIKE_TIPS.get(strike_view, '')} "
            f"Falls back to ATM if unavailable.</p>",
            unsafe_allow_html=True,
        )

    # Compute BS-IV and Greeks for each result's selected strike
    greeks_by_sym: dict[str, dict | None] = {}
    enriched_results: list[dict] = []
    for r in results:
        s = _get_strike(r, strike_view)
        r_copy = dict(r)
        if s:
            # Enrich strikes with BS-IV fallback
            enriched_stks = []
            for sk in r.get("strikes", []):
                sc = dict(sk)
                iv_e = sk.get("iv")
                ltp  = sk.get("premium")
                if iv_e is None and ltp and r.get("days_to_expiry"):
                    iv_e = _bs_iv(r["cmp"], sk["strike"], r["days_to_expiry"], ltp)
                sc["_iv_enriched"] = iv_e
                enriched_stks.append(sc)
            r_copy["strikes"] = enriched_stks
            # Greeks for selected strike
            sel_enriched = next(
                (sc for sc in enriched_stks if sc["strike_type"] == s["strike_type"]), None
            )
            iv_val = sel_enriched.get("_iv_enriched") if sel_enriched else None
            if iv_val and r.get("days_to_expiry") and sel_enriched:
                greeks_by_sym[r["symbol"]] = _bs_greeks(
                    S=r["cmp"], K=sel_enriched["strike"],
                    T_days=r["days_to_expiry"], sigma_pct=iv_val,
                    ltp_per_share=sel_enriched["premium"],
                )
            else:
                greeks_by_sym[r["symbol"]] = None
        else:
            greeks_by_sym[r["symbol"]] = None
        enriched_results.append(r_copy)

    # ── Comparison table ─────────────────────────────────────────────────────
    st.markdown(
        f'<div class="section-hd">Comparison Table — {strike_view} Strike</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        _cmp_table_html(enriched_results, strike_view, greeks_by_sym),
        unsafe_allow_html=True,
    )

    # CSV export (plain data, no Greeks)
    symbols_ok = [r["symbol"] for r in enriched_results]
    csv_rows: dict[str, list] = {}
    for r in enriched_results:
        s = _get_strike(r, strike_view)
        csv_rows.setdefault("CMP (₹)", []).append(r["cmp"])
        csv_rows.setdefault("Expiry", []).append(r["expiry_date"])
        csv_rows.setdefault("DTE", []).append(r["days_to_expiry"])
        csv_rows.setdefault("Strike (₹)", []).append(s["strike"] if s else None)
        csv_rows.setdefault("Net Premium (₹)", []).append(s["net_premium_total"] if s else None)
        csv_rows.setdefault("Ann. Yield %", []).append(s.get("annualised_yield_pct") if s else None)
        csv_rows.setdefault("Breakeven (₹)", []).append(s["breakeven"] if s else None)
        csv_rows.setdefault("Max Profit (₹)", []).append(s["max_profit_total"] if s else None)
        csv_rows.setdefault("Downside Prot. %", []).append(s["downside_protection_pct"] if s else None)

    csv_df = pd.DataFrame(csv_rows, index=symbols_ok)
    csv_buf = io.StringIO()
    csv_df.to_csv(csv_buf)
    st.download_button(
        label="⬇ Download Comparison CSV",
        data=csv_buf.getvalue().encode("utf-8"),
        file_name=f"breezy_compare_{strike_view}.csv",
        mime="text/csv",
    )

    # ── Per-instrument detail (transposed strike table) ───────────────────────
    st.divider()
    st.markdown('<div class="section-hd">Strike Detail per Instrument</div>',
                unsafe_allow_html=True)

    line_colors = ["#58A6FF", "#20A4A0", "#FF7B7B", "#FFD166", "#39D0C8"]

    for i, r in enumerate(enriched_results):
        with st.expander(
            f"{r['symbol']} — CMP ₹{r['cmp']:,.0f} · {r['days_to_expiry']}d · "
            f"Lot {r['lot_size']:,} · Capital ₹{r['position']['total_cost']:,.0f}",
            expanded=False,
        ):
            # Build per-instrument strike detail (same transposed format)
            r_greeks: dict[str, dict | None] = {}
            for sc in r.get("strikes", []):
                iv_e = sc.get("_iv_enriched")
                if iv_e and r.get("days_to_expiry"):
                    r_greeks[sc["strike_type"]] = _bs_greeks(
                        S=r["cmp"], K=sc["strike"],
                        T_days=r["days_to_expiry"], sigma_pct=iv_e,
                        ltp_per_share=sc["premium"],
                    )
                else:
                    r_greeks[sc["strike_type"]] = None

            # Reuse the app.py-style transposed table logic for one instrument
            stks = r.get("strikes", [])
            s_map = {s["strike_type"]: s for s in stks}
            types = [t for t in ("ITM", "ATM", "OTM+1", "OTM+2") if t in s_map]
            ncols = len(types) + 1
            CLR   = {"ITM": "#6A8FBF", "ATM": "#58A6FF", "OTM+1": "#20A4A0", "OTM+2": "#39D0C8"}

            hd = ("padding:7px 8px;border-bottom:2px solid #30363D;"
                  "color:#8B949E;font-size:11px;font-weight:600;white-space:nowrap;")
            td = ("padding:5px 8px;border-bottom:1px solid #21262D;"
                  "color:#C9D1D9;font-size:11px;text-align:right;"
                  "font-family:'Courier New',monospace;white-space:nowrap;")
            mtd = ("padding:5px 8px;border-bottom:1px solid #21262D;"
                   "color:#E6EDF3;font-size:11px;text-align:left;")
            shd = ("padding:4px 8px;background:#161B22;"
                   "color:#58A6FF;font-size:10px;font-weight:700;letter-spacing:0.5px;")

            def _fv(t, k, sk=None):
                s = s_map.get(t)
                if s is None: return None
                v = s.get(k)
                if sk is not None:
                    return v.get(sk) if isinstance(v, dict) else None
                return v

            def _gv2(t, k):
                g = r_greeks.get(t)
                return g.get(k) if g else None

            def _f(v, fmt):
                if v is None: return "—"
                try:
                    if fmt == "inr":   return f"₹{v:,.2f}"
                    if fmt == "inr0":  return f"₹{v:,.0f}"
                    if fmt == "pct1":  return f"{v:.1f}%"
                    if fmt == "pct2":  return f"{v:.2f}%"
                    if fmt == "spct1": return f"{v:+.1f}%"
                    if fmt == "int":   return f"{v:,}"
                    if fmt == "f4":    return f"{v:.4f}"
                    if fmt == "f6":    return f"{v:.6f}"
                    return str(v)
                except Exception: return "—"

            def sec2(title):
                return f'<tr><td colspan="{ncols}" style="{shd}">{title}</td></tr>'

            def row2(metric, vals, fmt):
                r2 = f'<tr><td style="{mtd}">{metric}</td>'
                for t in types:
                    r2 += f'<td style="{td}">{_f(vals.get(t), fmt)}</td>'
                return r2 + "</tr>"

            tbl = [
                '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;'
                'font-family:Inter,\'Segoe UI\',sans-serif;"><thead><tr>',
                f'<th style="{hd} text-align:left;min-width:140px;">Metric</th>',
            ]
            for t in types:
                s = s_map[t]
                clr = CLR.get(t, "#8B949E")
                tbl.append(
                    f'<th style="{hd} text-align:right;" >'
                    f'<span style="color:{clr};font-weight:700;">{t}</span><br>'
                    f'<span style="color:#E6EDF3;font-size:11px;">₹{s["strike"]:,.0f}</span>'
                    f'</th>'
                )
            tbl.append('</tr></thead><tbody>')
            tbl.append(sec2("── PREMIUM & INCOME ──"))
            tbl.append(row2("Gross LTP (₹/sh)", {t: _fv(t, "premium") for t in types}, "inr"))
            tbl.append(row2("Net Premium Total (₹)", {t: _fv(t, "net_premium_total") for t in types}, "inr"))
            tbl.append(row2("Ann. Yield %", {t: _fv(t, "annualised_yield_pct") for t in types}, "pct1"))
            tbl.append(sec2("── PERFORMANCE ──"))
            tbl.append(row2("Breakeven (₹)", {t: _fv(t, "breakeven") for t in types}, "inr0"))
            tbl.append(row2("Downside Prot. %", {t: _fv(t, "downside_protection_pct") for t in types}, "pct2"))
            tbl.append(row2("Max Profit (₹)", {t: _fv(t, "max_profit_total") for t in types}, "inr"))
            tbl.append(sec2("── MARKET DATA ──"))
            tbl.append(row2("IV %", {t: _fv(t, "_iv_enriched") or _fv(t, "iv") for t in types}, "pct1"))
            tbl.append(row2("Open Interest", {t: _fv(t, "open_interest") for t in types}, "int"))
            tbl.append(sec2("── GREEKS ──"))
            tbl.append(row2("Δ Delta", {t: _gv2(t, "delta") for t in types}, "f4"))
            tbl.append(row2("Θ Theta/day (₹/sh)", {t: _gv2(t, "theta_per_day") for t in types}, "inr"))
            tbl.append(row2("Implied Put (₹/sh)", {t: _gv2(t, "implied_put") for t in types}, "inr"))
            tbl.append('</tbody></table></div>')
            st.markdown("".join(tbl), unsafe_allow_html=True)

    # ── P&L Payoff chart (shown last) ─────────────────────────────────────────
    st.divider()
    st.markdown('<div class="section-hd">P&amp;L at Expiry — ATM Strikes</div>',
                unsafe_allow_html=True)
    st.caption("ATM P&L curves for cross-instrument comparison.")

    payoff_fig = go.Figure()
    for i, r in enumerate(enriched_results):
        atm = _get_strike(r, "ATM")
        if not atm or not atm.get("payoff"):
            continue
        xs = [p["price"] for p in atm["payoff"]]
        ys = [p["pl"]    for p in atm["payoff"]]
        payoff_fig.add_trace(go.Scatter(
            name=f"{r['symbol']} ATM ₹{atm['strike']:,.0f}",
            x=xs, y=ys,
            mode="lines+markers",
            line=dict(color=line_colors[i % len(line_colors)], width=2),
            marker=dict(size=4),
        ))
    payoff_fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="#8B949E")
    payoff_fig.update_layout(
        **_base_layout(height=320),
        title=dict(text="P&L at Expiry (ATM Strikes)", font=dict(size=14)),
        xaxis=dict(title="Stock price at expiry (₹)", showgrid=False, zeroline=False),
        yaxis=dict(title="P&L (₹)", showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
    )
    st.plotly_chart(payoff_fig, use_container_width=True, config={"displayModeBar": False})

else:
    st.markdown(
        "<p style='color:#8B949E; font-size:14px;'>"
        "Select 2–5 instruments above and click <b>Run Comparison ▶</b> to see results here."
        "</p>",
        unsafe_allow_html=True,
    )
